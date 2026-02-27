"""Tests for persistent queue module."""

import pytest
import threading
import time
from pathlib import Path

from src.watcher.queue import PersistentQueue
from src.watcher.exceptions import QueueError


class TestPersistentQueue:
    """Tests for PersistentQueue class."""

    def test_create_queue(self, tmp_path):
        db_path = tmp_path / "test.db"
        queue = PersistentQueue(db_path, "test_queue")
        assert db_path.exists()
        queue.close()

    def test_enqueue_dequeue_single(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            item_id = queue.enqueue({"key": "value"})
            assert item_id > 0
            
            items = queue.dequeue()
            assert len(items) == 1
            assert items[0][0] == item_id
            assert items[0][1] == {"key": "value"}

    def test_enqueue_dequeue_multiple(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"n": 1})
            queue.enqueue({"n": 2})
            queue.enqueue({"n": 3})
            
            items = queue.dequeue(batch_size=2)
            assert len(items) == 2
            assert items[0][1] == {"n": 1}
            assert items[1][1] == {"n": 2}

    def test_fifo_order(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            for i in range(5):
                queue.enqueue({"order": i})
            
            items = queue.dequeue(batch_size=5)
            for i, (_, item) in enumerate(items):
                assert item["order"] == i

    def test_enqueue_batch(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            items = [{"n": i} for i in range(10)]
            ids = queue.enqueue_batch(items)
            
            assert len(ids) == 10
            assert queue.size() == 10

    def test_enqueue_batch_empty(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            ids = queue.enqueue_batch([])
            assert ids == []

    def test_peek(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"data": "test"})
            
            # Peek should not remove items
            items1 = queue.peek()
            items2 = queue.peek()
            
            assert len(items1) == 1
            assert len(items2) == 1
            assert items1[0][1] == items2[0][1]

    def test_ack(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"data": 1})
            queue.enqueue({"data": 2})
            
            items = queue.dequeue()
            assert len(items) == 1
            
            queue.ack([items[0][0]])
            
            # Should get the second item now
            items2 = queue.dequeue()
            assert items2[0][1] == {"data": 2}

    def test_ack_empty(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.ack([])  # Should not raise

    def test_nack(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"data": "test"})
            
            items = queue.dequeue()
            item_id = items[0][0]
            
            # Nack should return item to queue
            queue.nack([item_id])
            
            items2 = queue.dequeue()
            assert len(items2) == 1
            assert items2[0][1] == {"data": "test"}

    def test_nack_empty(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.nack([])  # Should not raise

    def test_requeue_unacked(self, tmp_path):
        db_path = tmp_path / "test.db"
        
        # Simulate crash: dequeue without ack
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"data": "important"})
            queue.dequeue()  # Now in 'processing' state
        
        # Reopen and requeue
        with PersistentQueue(db_path, "test_queue") as queue:
            count = queue.requeue_unacked()
            assert count == 1
            
            items = queue.dequeue()
            assert len(items) == 1
            assert items[0][1] == {"data": "important"}

    def test_size(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            assert queue.size() == 0
            
            queue.enqueue({"n": 1})
            assert queue.size() == 1
            
            queue.enqueue({"n": 2})
            assert queue.size() == 2
            
            queue.dequeue()
            assert queue.size() == 1  # Dequeued item is now 'processing'

    def test_total_size(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"n": 1})
            queue.enqueue({"n": 2})
            
            items = queue.dequeue()
            
            # size() excludes processing items
            assert queue.size() == 1
            # total_size() includes all items
            assert queue.total_size() == 2

    def test_clear(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"n": 1})
            queue.enqueue({"n": 2})
            queue.enqueue({"n": 3})
            
            count = queue.clear()
            assert count == 3
            assert queue.size() == 0

    def test_dequeue_empty(self, tmp_path):
        db_path = tmp_path / "test.db"
        with PersistentQueue(db_path, "test_queue") as queue:
            items = queue.dequeue()
            assert items == []

    def test_queue_closed_error(self, tmp_path):
        db_path = tmp_path / "test.db"
        queue = PersistentQueue(db_path, "test_queue")
        queue.close()
        
        with pytest.raises(QueueError, match="Queue is closed"):
            queue.enqueue({"data": "test"})

    def test_queue_closed_dequeue_error(self, tmp_path):
        db_path = tmp_path / "test.db"
        queue = PersistentQueue(db_path, "test_queue")
        queue.close()
        
        with pytest.raises(QueueError, match="Queue is closed"):
            queue.dequeue()

    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "test.db"
        
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"data": "test"})
            assert queue.size() == 1

    def test_multiple_queues_same_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        
        with PersistentQueue(db_path, "queue1") as q1:
            with PersistentQueue(db_path, "queue2") as q2:
                q1.enqueue({"source": "q1"})
                q2.enqueue({"source": "q2"})
                
                items1 = q1.dequeue()
                items2 = q2.dequeue()
                
                assert items1[0][1] == {"source": "q1"}
                assert items2[0][1] == {"source": "q2"}

    def test_thread_safety_enqueue(self, tmp_path):
        db_path = tmp_path / "test.db"
        
        with PersistentQueue(db_path, "test_queue") as queue:
            threads = []
            errors = []
            
            def enqueue_items(start):
                try:
                    for i in range(10):
                        queue.enqueue({"n": start + i})
                except Exception as e:
                    errors.append(e)
            
            for t in range(5):
                thread = threading.Thread(target=enqueue_items, args=(t * 10,))
                threads.append(thread)
                thread.start()
            
            for thread in threads:
                thread.join()
            
            assert len(errors) == 0
            assert queue.size() == 50

    def test_thread_safety_dequeue(self, tmp_path):
        db_path = tmp_path / "test.db"
        
        with PersistentQueue(db_path, "test_queue") as queue:
            # Enqueue items
            for i in range(100):
                queue.enqueue({"n": i})
            
            results = []
            lock = threading.Lock()
            
            def dequeue_items():
                while True:
                    items = queue.dequeue(batch_size=5)
                    if not items:
                        break
                    with lock:
                        results.extend([item[1]["n"] for item in items])
                    queue.ack([item[0] for item in items])
            
            threads = [threading.Thread(target=dequeue_items) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            # All items should have been dequeued exactly once
            assert sorted(results) == list(range(100))

    def test_persistence_across_reopens(self, tmp_path):
        db_path = tmp_path / "test.db"
        
        # First open: enqueue items
        with PersistentQueue(db_path, "test_queue") as queue:
            queue.enqueue({"data": "persistent1"})
            queue.enqueue({"data": "persistent2"})
        
        # Second open: items should still be there
        with PersistentQueue(db_path, "test_queue") as queue:
            assert queue.size() == 2
            items = queue.dequeue(batch_size=2)
            assert items[0][1] == {"data": "persistent1"}
            assert items[1][1] == {"data": "persistent2"}

    def test_complex_data_types(self, tmp_path):
        db_path = tmp_path / "test.db"
        
        with PersistentQueue(db_path, "test_queue") as queue:
            complex_data = {
                "string": "hello",
                "number": 42,
                "float": 3.14,
                "bool": True,
                "null": None,
                "list": [1, 2, 3],
                "nested": {"a": {"b": {"c": 1}}},
            }
            queue.enqueue(complex_data)
            
            items = queue.dequeue()
            assert items[0][1] == complex_data

    def test_double_close(self, tmp_path):
        db_path = tmp_path / "test.db"
        queue = PersistentQueue(db_path, "test_queue")
        queue.close()
        queue.close()  # Should not raise
