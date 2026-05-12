#!/usr/bin/env python3
"""Simplified WebSocket load test for TopicWebSocketManager.

Tests connection scalability and basic message handling.
"""

import asyncio
import argparse
import json
import time
import statistics
import psutil
import os
from datetime import datetime

try:
    import websockets
except ImportError:
    print("ERROR: websockets library not installed")
    print("Install with: pip install websockets")
    exit(1)


async def test_client(client_id, endpoint, base_url, duration):
    """Single client that connects, subscribes, and listens."""
    url = f"{base_url}/ws/{endpoint}"
    connected = False
    messages_received = 0
    errors = []
    latencies = []
    
    try:
        ws = await asyncio.wait_for(
            websockets.connect(url),
            timeout=10
        )
        connected = True
        print(f"Client {client_id}: Connected", flush=True)
        
        await ws.send(json.dumps({"action": "subscribe", "topic": endpoint}))
        print(f"Client {client_id}: Sent subscribe", flush=True)
        
        response = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(response)
        print(f"Client {client_id}: Got response {data.get('type')}", flush=True)
        
        if data.get("type") not in ["subscribed", "connected", "success"]:
            errors.append(f"Unexpected response: {data}")
            await ws.close()
            return {
                "client_id": client_id,
                "connected": False,
                "messages": 0,
                "errors": errors,
                "latencies": []
            }
        
        start_time = time.time()
        
        while time.time() - start_time < duration:
            try:
                remaining = duration - (time.time() - start_time)
                if remaining <= 0:
                    break
                timeout = min(35, remaining + 1)
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                msg_data = json.loads(msg)
                msg_type = msg_data.get("type")
                
                if msg_type == "heartbeat":
                    messages_received += 1
                elif msg_type in ["market_update", "whale_alert", "activity", "brain_update", "event"]:
                    messages_received += 1
                    
                    if "timestamp" in msg_data:
                        sent_time = msg_data["timestamp"]
                        if isinstance(sent_time, str):
                            sent_time = datetime.fromisoformat(sent_time.replace('Z', '+00:00')).timestamp()
                        latency_ms = (time.time() - sent_time) * 1000
                        latencies.append(latency_ms)
                        
            except asyncio.TimeoutError:
                errors.append("Timeout waiting for message")
                break
            except json.JSONDecodeError as e:
                errors.append(f"JSON error: {e}")
        
        print(f"Client {client_id}: Closing after {time.time()-start_time:.1f}s", flush=True)
        await ws.close()
        
    except asyncio.TimeoutError:
        errors.append("Connection timeout")
    except Exception as e:
        errors.append(f"Error: {type(e).__name__}: {e}")
    
    return {
        "client_id": client_id,
        "connected": connected,
        "messages": messages_received,
        "errors": errors,
        "latencies": latencies
    }


async def run_load_test(num_clients, endpoint, base_url, duration):
    """Run load test with multiple concurrent clients."""
    print(f"\n{'='*70}")
    print("WebSocket Load Test - TopicWebSocketManager")
    print(f"{'='*70}")
    print(f"Endpoint: {endpoint}")
    print(f"Clients: {num_clients}")
    print(f"Duration: {duration}s")
    print(f"Base URL: {base_url}")
    print(f"{'='*70}\n")
    
    process = psutil.Process(os.getpid())
    initial_cpu = process.cpu_percent(interval=1)
    initial_memory = process.memory_info().rss / 1024 / 1024 / 1024
    
    cpu_samples = []
    memory_samples = []
    
    async def monitor_resources():
        while True:
            await asyncio.sleep(10)
            cpu = process.cpu_percent(interval=1)
            memory = process.memory_info().rss / 1024 / 1024 / 1024
            cpu_samples.append(cpu)
            memory_samples.append(memory)
    
    print("Phase 1: Connecting clients...")
    start_time = time.time()
    
    tasks = [
        test_client(i, endpoint, base_url, duration)
        for i in range(num_clients)
    ]
    
    print(f"Starting {num_clients} concurrent clients...")
    
    monitor_task = asyncio.create_task(monitor_resources())
    results = await asyncio.gather(*tasks, return_exceptions=True)
    monitor_task.cancel()
    
    print("All clients completed.")
    
    end_time = time.time()
    
    final_cpu = process.cpu_percent(interval=1)
    final_memory = process.memory_info().rss / 1024 / 1024 / 1024
    
    print("\nPhase 2: Analyzing results...")
    
    successful_results = [r for r in results if isinstance(r, dict)]
    exceptions = [r for r in results if not isinstance(r, dict)]
    
    connected_count = sum(1 for r in successful_results if r["connected"])
    total_messages = sum(r["messages"] for r in successful_results)
    all_errors = []
    all_latencies = []
    
    for r in successful_results:
        all_errors.extend(r["errors"])
        all_latencies.extend(r["latencies"])
    
    latency_stats = {}
    if all_latencies:
        all_latencies.sort()
        latency_stats = {
            "p50": statistics.median(all_latencies),
            "p95": all_latencies[int(len(all_latencies) * 0.95)] if len(all_latencies) > 1 else all_latencies[0],
            "p99": all_latencies[int(len(all_latencies) * 0.99)] if len(all_latencies) > 1 else all_latencies[0],
            "min": min(all_latencies),
            "max": max(all_latencies),
            "mean": statistics.mean(all_latencies),
        }
    
    avg_cpu = statistics.mean(cpu_samples) if cpu_samples else final_cpu
    max_cpu = max(cpu_samples) if cpu_samples else final_cpu
    avg_memory = statistics.mean(memory_samples) if memory_samples else final_memory
    max_memory = max(memory_samples) if memory_samples else final_memory
    
    report = {
        "test_config": {
            "num_clients": num_clients,
            "endpoint": endpoint,
            "duration": duration,
            "base_url": base_url,
        },
        "connection_stats": {
            "connected": connected_count,
            "disconnected": num_clients - connected_count,
            "success_rate": f"{(connected_count / num_clients * 100):.1f}%",
        },
        "message_stats": {
            "total_messages": total_messages,
            "messages_per_client": total_messages / num_clients if num_clients > 0 else 0,
            "messages_per_second": total_messages / duration if duration > 0 else 0,
        },
        "latency_stats": latency_stats,
        "resource_usage": {
            "initial_cpu_percent": initial_cpu,
            "final_cpu_percent": final_cpu,
            "avg_cpu_percent": avg_cpu,
            "max_cpu_percent": max_cpu,
            "cpu_delta": final_cpu - initial_cpu,
            "initial_memory_gb": initial_memory,
            "final_memory_gb": final_memory,
            "avg_memory_gb": avg_memory,
            "max_memory_gb": max_memory,
            "memory_delta_gb": final_memory - initial_memory,
        },
        "errors": {
            "total_errors": len(all_errors),
            "exceptions": len(exceptions),
            "unique_errors": list(set(all_errors))[:10],
        },
        "test_duration": end_time - start_time,
    }
    
    print_report(report)
    return report


def print_report(report):
    """Print formatted test report."""
    print(f"\n{'='*70}")
    print("LOAD TEST RESULTS")
    print(f"{'='*70}\n")
    
    conn = report["connection_stats"]
    print("CONNECTION STATS:")
    print(f"  Connected: {conn['connected']}/{report['test_config']['num_clients']}")
    print(f"  Success Rate: {conn['success_rate']}")
    print(f"  Disconnected: {conn['disconnected']}")
    
    msg = report["message_stats"]
    print("\nMESSAGE STATS:")
    print(f"  Total Messages: {msg['total_messages']}")
    print(f"  Messages/Client: {msg['messages_per_client']:.1f}")
    print(f"  Messages/Second: {msg['messages_per_second']:.2f}")
    
    if report["latency_stats"]:
        print("\nLATENCY STATS (ms):")
        lat = report["latency_stats"]
        print(f"  p50: {lat['p50']:.2f}ms")
        print(f"  p95: {lat['p95']:.2f}ms")
        print(f"  p99: {lat['p99']:.2f}ms")
        print(f"  Min: {lat['min']:.2f}ms")
        print(f"  Max: {lat['max']:.2f}ms")
        print(f"  Mean: {lat['mean']:.2f}ms")
        
        if lat['p99'] < 200:
            print("  ✓ PASS: p99 latency < 200ms")
        else:
            print("  ✗ FAIL: p99 latency >= 200ms")
    else:
        print("\nLATENCY STATS: No latency data (no timestamped messages)")
    
    res = report["resource_usage"]
    print("\nRESOURCE USAGE:")
    print(f"  CPU: {res['initial_cpu_percent']:.1f}% → {res['final_cpu_percent']:.1f}% (Δ {res['cpu_delta']:+.1f}%)")
    print(f"  CPU Avg: {res['avg_cpu_percent']:.1f}% | Max: {res['max_cpu_percent']:.1f}%")
    print(f"  Memory: {res['initial_memory_gb']:.2f}GB → {res['final_memory_gb']:.2f}GB (Δ {res['memory_delta_gb']:+.2f}GB)")
    print(f"  Memory Avg: {res['avg_memory_gb']:.2f}GB | Max: {res['max_memory_gb']:.2f}GB")
    
    cpu_ok = res['max_cpu_percent'] < 80
    memory_ok = res['max_memory_gb'] < 2.0
    print(f"  {'✓' if cpu_ok else '✗'} CPU Target: <80% (Max: {res['max_cpu_percent']:.1f}%)")
    print(f"  {'✓' if memory_ok else '✗'} Memory Target: <2GB (Max: {res['max_memory_gb']:.2f}GB)")
    
    err = report["errors"]
    print("\nERROR STATS:")
    print(f"  Total Errors: {err['total_errors']}")
    print(f"  Exceptions: {err['exceptions']}")
    if err['unique_errors']:
        print("  Sample Errors:")
        for error in err['unique_errors'][:5]:
            print(f"    - {error}")
    
    print(f"\n{'='*70}")
    conn_ok = conn['connected'] == report['test_config']['num_clients']
    latency_ok = not report["latency_stats"] or report["latency_stats"]["p99"] < 200
    errors_ok = err['total_errors'] == 0 and err['exceptions'] == 0
    
    res = report["resource_usage"]
    cpu_ok = res['max_cpu_percent'] < 80
    memory_ok = res['max_memory_gb'] < 2.0
    
    all_ok = conn_ok and latency_ok and errors_ok and cpu_ok and memory_ok
    
    if all_ok:
        print("✓ OVERALL: PASS - All targets met")
    else:
        print("✗ OVERALL: FAIL")
        if not conn_ok:
            print(f"  - Connection drops detected ({conn['disconnected']} clients)")
        if not latency_ok:
            print("  - Latency p99 >= 200ms")
        if not errors_ok:
            print(f"  - Errors detected ({err['total_errors']} errors, {err['exceptions']} exceptions)")
        if not cpu_ok:
            print(f"  - CPU exceeded 80% (Max: {res['max_cpu_percent']:.1f}%)")
        if not memory_ok:
            print(f"  - Memory exceeded 2GB (Max: {res['max_memory_gb']:.2f}GB)")
    print(f"{'='*70}\n")
    
    print(f"Test Duration: {report['test_duration']:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="WebSocket Load Test (Simplified)")
    parser.add_argument("--clients", type=int, default=100, help="Number of concurrent clients")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--endpoint", type=str, default="markets", 
                       choices=["markets", "whales", "activities", "brain", "events"],
                       help="WebSocket endpoint to test")
    parser.add_argument("--base-url", type=str, default="ws://localhost:8100",
                       help="Base WebSocket URL")
    parser.add_argument("--output", type=str, default=None,
                       help="Output file for JSON report")
    
    args = parser.parse_args()
    
    report = asyncio.run(run_load_test(
        args.clients,
        args.endpoint,
        args.base_url,
        args.duration
    ))
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {args.output}")


if __name__ == "__main__":
    main()
