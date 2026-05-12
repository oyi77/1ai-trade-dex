#!/usr/bin/env python3
import asyncio
import websockets
import json
import sys
from datetime import datetime


async def test_reconnection(url="ws://localhost:8000/ws/activities", token="", cycles=3):
    uri = f"{url}?token={token}" if token else url
    
    print(f"Testing WebSocket reconnection to {uri}")
    print(f"Will connect, disconnect, and reconnect {cycles} times\n")
    
    for cycle in range(1, cycles + 1):
        print(f"=== Cycle {cycle}/{cycles} ===")
        
        try:
            async with websockets.connect(uri) as websocket:
                connect_time = datetime.now()
                print(f"✓ Connected at {connect_time.isoformat()}")
                
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(message)
                    print(f"✓ Received first message: {data.get('type', 'unknown')}")
                except asyncio.TimeoutError:
                    print("✓ No immediate message (expected)")
                
                print("  Staying connected for 2 seconds...")
                await asyncio.sleep(2)
                
                print("✓ Disconnecting gracefully...")
            
            disconnect_time = datetime.now()
            duration = (disconnect_time - connect_time).total_seconds()
            print(f"✓ Disconnected after {duration:.2f}s\n")
            
            if cycle < cycles:
                print("  Waiting 1 second before reconnecting...")
                await asyncio.sleep(1)
        
        except ConnectionRefusedError:
            print("✗ Connection refused. Is the server running?")
            return 1
        except Exception as e:
            print(f"✗ Error in cycle {cycle}: {e}")
            return 1
    
    print(f"\n✓ All {cycles} reconnection cycles completed successfully!")
    return 0


async def test_concurrent_connections(url="ws://localhost:8000/ws/activities", token="", count=5):
    uri = f"{url}?token={token}" if token else url
    
    print(f"\nTesting {count} concurrent connections to {uri}\n")
    
    async def single_connection(client_id):
        try:
            async with websockets.connect(uri) as websocket:
                print(f"✓ Client {client_id} connected")
                
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    data = json.loads(message)
                    print(f"✓ Client {client_id} received: {data.get('type', 'unknown')}")
                except asyncio.TimeoutError:
                    print(f"✓ Client {client_id} no immediate message")
                
                await asyncio.sleep(2)
                print(f"✓ Client {client_id} disconnecting")
            
            return True
        except Exception as e:
            print(f"✗ Client {client_id} error: {e}")
            return False
    
    tasks = [single_connection(i+1) for i in range(count)]
    results = await asyncio.gather(*tasks)
    
    success_count = sum(results)
    print(f"\n✓ {success_count}/{count} clients completed successfully")
    
    return 0 if success_count == count else 1


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000/ws/activities"
    token = sys.argv[2] if len(sys.argv) > 2 else ""
    
    try:
        print("=" * 60)
        print("WebSocket Reconnection Test")
        print("=" * 60 + "\n")
        
        exit_code = asyncio.run(test_reconnection(url, token, cycles=3))
        
        if exit_code == 0:
            exit_code = asyncio.run(test_concurrent_connections(url, token, count=5))
        
        print("\n" + "=" * 60)
        if exit_code == 0:
            print("✓ ALL TESTS PASSED")
        else:
            print("✗ SOME TESTS FAILED")
        print("=" * 60)
        
        sys.exit(exit_code)
    
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
