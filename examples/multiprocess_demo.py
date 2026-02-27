#!/usr/bin/env python3
"""
Multi-process file watcher demo.

This example demonstrates:
1. Watcher process - runs the file watcher
2. Event consumer process - receives and prints file events
3. Root manager process - dynamically adds/removes watched roots

Usage:
    python examples/multiprocess_demo.py

The demo will:
- Create a temporary directory structure
- Start 3 processes
- Add roots dynamically
- Create/modify/delete files
- Show events being received
- Remove roots
- Clean up after 30 seconds
"""

import multiprocessing
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from watcher import WatcherProcess, WatcherConfig, EventType


def watcher_process(db_path: Path, stop_event: multiprocessing.Event):
    """
    Process 1: Runs the file watcher.
    
    This process hosts the WatcherProcess and handles filesystem monitoring.
    """
    print(f"[WATCHER] Starting watcher process (PID: {os.getpid()})")
    
    config = WatcherConfig(
        db_path=db_path,
        debounce_ms=50,
        batch_timeout_ms=200,
        move_correlation_ms=100,
    )
    
    with WatcherProcess(config=config) as watcher:
        watcher.start_async()
        print("[WATCHER] Watcher is running, waiting for commands...")
        
        # Keep running until stop event is set
        while not stop_event.is_set():
            time.sleep(0.1)
        
        print("[WATCHER] Stopping watcher...")
    
    print("[WATCHER] Watcher process exited")


def event_consumer_process(db_path: Path, stop_event: multiprocessing.Event):
    """
    Process 2: Consumes file events from the queue.
    
    This process reads events from the persistent queue and prints them.
    """
    print(f"[CONSUMER] Starting event consumer process (PID: {os.getpid()})")
    
    # Wait a moment for watcher to initialize
    time.sleep(1)
    
    config = WatcherConfig(db_path=db_path)
    
    with WatcherProcess(config=config) as consumer:
        print("[CONSUMER] Listening for file events...")
        
        while not stop_event.is_set():
            # Get pending events (non-blocking)
            events = consumer.get_pending_events(max_count=10)
            
            for event in events:
                event_icon = {
                    EventType.ADD: "➕",
                    EventType.DELETE: "❌",
                    EventType.UPDATE: "📝",
                    EventType.MOVE: "📦",
                }.get(event.event_type, "❓")
                
                print(f"[CONSUMER] {event_icon} {event.event_type.value.upper()}: {event.path}")
                if event.content_hash:
                    print(f"           Hash: {event.content_hash[:16]}...")
                if event.old_path:
                    print(f"           From: {event.old_path}")
            
            time.sleep(0.2)
    
    print("[CONSUMER] Event consumer process exited")


def root_manager_process(db_path: Path, demo_dir: Path, stop_event: multiprocessing.Event):
    """
    Process 3: Manages roots and creates test files.
    
    This process adds/removes roots and creates test files to trigger events.
    """
    print(f"[MANAGER] Starting root manager process (PID: {os.getpid()})")
    
    # Wait for watcher to initialize
    time.sleep(2)
    
    config = WatcherConfig(db_path=db_path)
    
    with WatcherProcess(config=config) as manager:
        # Create demo directories
        root1 = demo_dir / "watched_folder_1"
        root2 = demo_dir / "watched_folder_2"
        root1.mkdir(parents=True, exist_ok=True)
        root2.mkdir(parents=True, exist_ok=True)
        
        # === Step 1: Add first root ===
        print(f"\n[MANAGER] Adding root: {root1}")
        manager.add_root(root1)
        time.sleep(1)
        
        # === Step 2: Create some files ===
        print("\n[MANAGER] Creating files in root1...")
        (root1 / "hello.txt").write_text("Hello, World!")
        time.sleep(0.5)
        (root1 / "data.json").write_text('{"key": "value"}')
        time.sleep(0.5)
        
        # === Step 3: Modify a file ===
        print("\n[MANAGER] Modifying hello.txt...")
        (root1 / "hello.txt").write_text("Hello, Updated World!")
        time.sleep(0.5)
        
        # === Step 4: Add second root ===
        print(f"\n[MANAGER] Adding second root: {root2}")
        manager.add_root(root2)
        time.sleep(1)
        
        # === Step 5: Create files in second root ===
        print("\n[MANAGER] Creating files in root2...")
        (root2 / "document.md").write_text("# Document\n\nSome content here.")
        time.sleep(0.5)
        
        # === Step 6: Create subdirectory ===
        print("\n[MANAGER] Creating subdirectory with files...")
        subdir = root1 / "subdir"
        subdir.mkdir(exist_ok=True)
        (subdir / "nested.txt").write_text("Nested file content")
        time.sleep(0.5)
        
        # === Step 7: Move a file ===
        print("\n[MANAGER] Moving file within root1...")
        (root1 / "data.json").rename(root1 / "config.json")
        time.sleep(0.5)
        
        # === Step 8: Delete a file ===
        print("\n[MANAGER] Deleting a file...")
        (root1 / "hello.txt").unlink()
        time.sleep(0.5)
        
        # === Step 9: Move file between roots ===
        print("\n[MANAGER] Moving file from root1 to root2...")
        (root1 / "config.json").rename(root2 / "config.json")
        time.sleep(0.5)
        
        # === Step 10: Remove first root ===
        print(f"\n[MANAGER] Removing root: {root1}")
        manager.remove_root(root1)
        time.sleep(1)
        
        # Create file in removed root (should not trigger events)
        print("\n[MANAGER] Creating file in removed root (no events expected)...")
        (root1 / "ignored.txt").write_text("This should be ignored")
        time.sleep(0.5)
        
        # Create file in remaining root
        print("\n[MANAGER] Creating file in still-watched root2...")
        (root2 / "final.txt").write_text("Final file")
        time.sleep(1)
        
        print("\n[MANAGER] Demo complete! Waiting 3 seconds before shutdown...")
        time.sleep(3)
        
        # Signal all processes to stop
        stop_event.set()
    
    print("[MANAGER] Root manager process exited")


def main():
    """Run the multi-process demo."""
    import tempfile
    import shutil
    
    print("=" * 60)
    print("File Watcher Multi-Process Demo")
    print("=" * 60)
    
    # Create temporary directory for demo
    demo_dir = Path(tempfile.mkdtemp(prefix="watcher_demo_"))
    db_path = demo_dir / "watcher.db"
    
    print(f"\nDemo directory: {demo_dir}")
    print(f"Database path: {db_path}")
    print()
    
    # Create stop event for graceful shutdown
    stop_event = multiprocessing.Event()
    
    # Create processes
    processes = [
        multiprocessing.Process(
            target=watcher_process,
            args=(db_path, stop_event),
            name="WatcherProcess"
        ),
        multiprocessing.Process(
            target=event_consumer_process,
            args=(db_path, stop_event),
            name="EventConsumer"
        ),
        multiprocessing.Process(
            target=root_manager_process,
            args=(db_path, demo_dir, stop_event),
            name="RootManager"
        ),
    ]
    
    try:
        # Start all processes
        for p in processes:
            p.start()
        
        # Wait for all processes to complete
        for p in processes:
            p.join()
        
        print("\n" + "=" * 60)
        print("Demo completed successfully!")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted! Stopping all processes...")
        stop_event.set()
        for p in processes:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()
    
    finally:
        # Cleanup
        print(f"\nCleaning up demo directory: {demo_dir}")
        shutil.rmtree(demo_dir, ignore_errors=True)


if __name__ == "__main__":
    # Required for macOS
    multiprocessing.set_start_method("spawn", force=True)
    main()
