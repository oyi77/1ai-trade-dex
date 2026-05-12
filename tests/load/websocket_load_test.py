#!/usr/bin/env python3
"""WebSocket load test for TopicWebSocketManager.

Tests scalability of TopicWebSocketManager with 100 concurrent clients.
Measures message delivery latency, connection stability, and resource usage.

Usage:
    python tests/load/websocket_load_test.py --clients 100 --duration 300
    python tests/load/websocket_load_test.py --clients 50 --endpoint markets
"""

import asyncio
import argparse
import json
import time
import statistics
import psutil
import os
from typing import List, Dict, Any
from datetime import datetime

try:
    import websockets
except ImportError:
    print("ERROR: websockets library not installed")
    print("Install with: pip install websockets")
    exit(1)


class WebSocketClient:
    """Single WebSocket client for load testing."""
    
    def __init__(self, client_id: int, endpoint: str, base_url: str, token: str = ""):
        self.client_id = client_id
        self.endpoint = endpoint
        self.url = f"{base_url}/ws/{endpoint}"
        if token:
            self.url += f"?token={token}"
        self.websocket = None
        self.connected = False
        self.messages_received = 0
        self.latencies = []
        self.errors = []
        self.last_heartbeat = None
        
    async def connect(self):
        """Connect to WebSocket endpoint and subscribe to topic."""
        try:
            self.websocket = await websockets.connect(self.url)
            self.connected = True
            
            # Send subscription message
            await self.websocket.send(json.dumps({
                "action": "subscribe",
                "topic": self.endpoint
            }))
            
            # Wait for subscription confirmation
            response = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=5.0
            )
            data = json.loads(response)
            if data.get("type") not in ["subscribed", "connected"]:
                raise Exception(f"Subscription failed: {data}")
                
            return True
        except Exception as e:
            self.errors.append(f"Connection error: {e}")
            self.connected = False
            return False
    
    async def listen(self, duration: int):
        """Listen for messages for specified duration."""
        if not self.connected:
            return
            
        start_time = time.time()
        
        try:
            while time.time() - start_time < duration:
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=35.0  # Slightly longer than heartbeat interval
                    )
                    
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "heartbeat":
                        self.last_heartbeat = time.time()
                        self.messages_received += 1
                    elif msg_type in ["market_update", "whale_alert", "activity", "brain_update", "event"]:
                        if "timestamp" in data:
                            sent_time = data["timestamp"]
                            if isinstance(sent_time, str):
                                sent_time = datetime.fromisoformat(sent_time.replace('Z', '+00:00')).timestamp()
                            latency_ms = (time.time() - sent_time) * 1000
                            self.latencies.append(latency_ms)
                        
                        self.messages_received += 1
                    
                except asyncio.TimeoutError:
                    self.errors.append("Timeout waiting for message")
                    break
                except json.JSONDecodeError as e:
                    self.errors.append(f"JSON decode error: {e}")
                    
        except Exception as e:
            self.errors.append(f"Listen error: {e}")
        finally:
            await self.disconnect()
    
    async def disconnect(self):
        """Close WebSocket connection."""
        if self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
        self.connected = False


class LoadTestRunner:
    """Orchestrates load test with multiple concurrent clients."""
    
    def __init__(self, num_clients: int, endpoint: str, base_url: str, 
                 duration: int, token: str = "", churn: bool = False, 
                 broadcast_rate: int = 0):
        self.num_clients = num_clients
        self.endpoint = endpoint
        self.base_url = base_url
        self.duration = duration
        self.token = token
        self.churn = churn
        self.broadcast_rate = broadcast_rate
        self.clients: List[WebSocketClient] = []
        self.start_time = None
        self.end_time = None
        self.process = psutil.Process(os.getpid())
        self.cpu_samples = []
        self.memory_samples = []
        self.sample_interval = 10  # Sample every 10 seconds
        
    async def monitor_resources(self):
        """Continuously monitor CPU and memory during test."""
        while time.time() - self.start_time < self.duration:
            cpu = self.process.cpu_percent(interval=1)
            memory = self.process.memory_info().rss / 1024 / 1024 / 1024
            self.cpu_samples.append(cpu)
            self.memory_samples.append(memory)
            await asyncio.sleep(self.sample_interval)
    
    async def churn_clients(self):
        """Simulate connection churn by cycling clients."""
        churn_interval = 30
        while time.time() - self.start_time < self.duration:
            await asyncio.sleep(churn_interval)
            
            num_to_churn = max(1, self.num_clients // 10)
            print(f"  [Churn] Cycling {num_to_churn} clients...")
            
            for i in range(num_to_churn):
                if i < len(self.clients):
                    await self.clients[i].disconnect()
                    new_client = WebSocketClient(i, self.endpoint, self.base_url, self.token)
                    if await new_client.connect():
                        asyncio.create_task(new_client.listen(self.duration - (time.time() - self.start_time)))
                        self.clients[i] = new_client
    
    async def run(self):
        """Execute load test."""
        print(f"\n{'='*70}")
        print("WebSocket Load Test - TopicWebSocketManager")
        print(f"{'='*70}")
        print(f"Endpoint: {self.endpoint}")
        print(f"Clients: {self.num_clients}")
        print(f"Duration: {self.duration}s")
        print(f"Base URL: {self.base_url}")
        if self.churn:
            print("Churn: ENABLED (10% clients every 30s)")
        if self.broadcast_rate > 0:
            print(f"Target Broadcast Rate: {self.broadcast_rate} msg/s")
        print(f"{'='*70}\n")
        
        initial_cpu = self.process.cpu_percent(interval=1)
        initial_memory = self.process.memory_info().rss / 1024 / 1024 / 1024
        
        print("Phase 1: Connecting clients...")
        self.start_time = time.time()
        
        self.clients = [
            WebSocketClient(i, self.endpoint, self.base_url, self.token)
            for i in range(self.num_clients)
        ]
        
        connection_tasks = [client.connect() for client in self.clients]
        connection_results = await asyncio.gather(*connection_tasks, return_exceptions=True)
        
        connected_count = sum(1 for r in connection_results if r is True)
        print(f"✓ Connected: {connected_count}/{self.num_clients} clients")
        
        if connected_count == 0:
            print("✗ FAILED: No clients connected")
            return self.generate_report(initial_cpu, initial_memory)
        
        print(f"\nPhase 2: Listening for {self.duration}s...")
        print("(Monitoring resources every {self.sample_interval}s...)\n")
        
        background_tasks = [
            asyncio.create_task(self.monitor_resources())
        ]
        
        if self.churn:
            background_tasks.append(asyncio.create_task(self.churn_clients()))
        
        listen_tasks = [client.listen(self.duration) for client in self.clients]
        await asyncio.gather(*listen_tasks, *background_tasks, return_exceptions=True)
        
        self.end_time = time.time()
        
        final_cpu = self.process.cpu_percent(interval=1)
        final_memory = self.process.memory_info().rss / 1024 / 1024 / 1024
        
        print("\nPhase 3: Generating report...")
        return self.generate_report(initial_cpu, initial_memory, final_cpu, final_memory)
    
    def generate_report(self, initial_cpu: float, initial_memory: float,
                       final_cpu: float = None, final_memory: float = None) -> Dict[str, Any]:
        """Generate comprehensive test report."""
        total_messages = sum(c.messages_received for c in self.clients)
        all_latencies = []
        for c in self.clients:
            all_latencies.extend(c.latencies)
        
        all_errors = []
        for c in self.clients:
            all_errors.extend(c.errors)
        
        connected_clients = sum(1 for c in self.clients if c.connected or c.messages_received > 0)
        disconnected_clients = self.num_clients - connected_clients
        
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
        
        cpu_delta = final_cpu - initial_cpu if final_cpu else 0
        memory_delta = final_memory - initial_memory if final_memory else 0
        
        avg_cpu = statistics.mean(self.cpu_samples) if self.cpu_samples else final_cpu
        max_cpu = max(self.cpu_samples) if self.cpu_samples else final_cpu
        avg_memory = statistics.mean(self.memory_samples) if self.memory_samples else final_memory
        max_memory = max(self.memory_samples) if self.memory_samples else final_memory
        
        report = {
            "test_config": {
                "num_clients": self.num_clients,
                "endpoint": self.endpoint,
                "duration": self.duration,
                "base_url": self.base_url,
                "churn_enabled": self.churn,
                "broadcast_rate": self.broadcast_rate,
            },
            "connection_stats": {
                "connected": connected_clients,
                "disconnected": disconnected_clients,
                "success_rate": f"{(connected_clients / self.num_clients * 100):.1f}%",
            },
            "message_stats": {
                "total_messages": total_messages,
                "messages_per_client": total_messages / self.num_clients if self.num_clients > 0 else 0,
                "messages_per_second": total_messages / self.duration if self.duration > 0 else 0,
            },
            "latency_stats": latency_stats,
            "resource_usage": {
                "initial_cpu_percent": initial_cpu,
                "final_cpu_percent": final_cpu,
                "avg_cpu_percent": avg_cpu,
                "max_cpu_percent": max_cpu,
                "cpu_delta": cpu_delta,
                "initial_memory_gb": initial_memory,
                "final_memory_gb": final_memory,
                "avg_memory_gb": avg_memory,
                "max_memory_gb": max_memory,
                "memory_delta_gb": memory_delta,
            },
            "errors": {
                "total_errors": len(all_errors),
                "error_rate": f"{(len(all_errors) / self.num_clients * 100):.1f}%",
                "unique_errors": list(set(all_errors))[:10],
            },
            "test_duration": self.end_time - self.start_time if self.end_time else 0,
        }
        
        self.print_report(report)
        return report
    
    def print_report(self, report: Dict[str, Any]):
        """Print formatted test report."""
        print(f"\n{'='*70}")
        print("LOAD TEST RESULTS")
        print(f"{'='*70}\n")
        
        # Connection stats
        print("CONNECTION STATS:")
        conn = report["connection_stats"]
        print(f"  Connected: {conn['connected']}/{report['test_config']['num_clients']}")
        print(f"  Success Rate: {conn['success_rate']}")
        print(f"  Disconnected: {conn['disconnected']}")
        
        # Message stats
        print("\nMESSAGE STATS:")
        msg = report["message_stats"]
        print(f"  Total Messages: {msg['total_messages']}")
        print(f"  Messages/Client: {msg['messages_per_client']:.1f}")
        print(f"  Messages/Second: {msg['messages_per_second']:.2f}")
        
        # Latency stats
        if report["latency_stats"]:
            print("\nLATENCY STATS (ms):")
            lat = report["latency_stats"]
            print(f"  p50: {lat['p50']:.2f}ms")
            print(f"  p95: {lat['p95']:.2f}ms")
            print(f"  p99: {lat['p99']:.2f}ms")
            print(f"  Min: {lat['min']:.2f}ms")
            print(f"  Max: {lat['max']:.2f}ms")
            print(f"  Mean: {lat['mean']:.2f}ms")
            
            # Check p99 requirement
            if lat['p99'] < 200:
                print("  ✓ PASS: p99 latency < 200ms")
            else:
                print("  ✗ FAIL: p99 latency >= 200ms")
        else:
            print("\nLATENCY STATS: No latency data (no timestamped messages received)")
        
        # Resource usage
        print("\nRESOURCE USAGE:")
        res = report["resource_usage"]
        if res["final_cpu_percent"]:
            print(f"  CPU: {res['initial_cpu_percent']:.1f}% → {res['final_cpu_percent']:.1f}% (Δ {res['cpu_delta']:+.1f}%)")
            print(f"  CPU Avg: {res['avg_cpu_percent']:.1f}% | Max: {res['max_cpu_percent']:.1f}%")
            print(f"  Memory: {res['initial_memory_gb']:.2f}GB → {res['final_memory_gb']:.2f}GB (Δ {res['memory_delta_gb']:+.2f}GB)")
            print(f"  Memory Avg: {res['avg_memory_gb']:.2f}GB | Max: {res['max_memory_gb']:.2f}GB")
            
            cpu_ok = res['max_cpu_percent'] < 80
            memory_ok = res['max_memory_gb'] < 2.0
            print(f"  {'✓' if cpu_ok else '✗'} CPU Target: <80% (Max: {res['max_cpu_percent']:.1f}%)")
            print(f"  {'✓' if memory_ok else '✗'} Memory Target: <2GB (Max: {res['max_memory_gb']:.2f}GB)")
        else:
            print(f"  CPU: {res['initial_cpu_percent']:.1f}%")
            print(f"  Memory: {res['initial_memory_gb']:.2f}GB")
        
        # Errors
        print("\nERROR STATS:")
        err = report["errors"]
        print(f"  Total Errors: {err['total_errors']}")
        print(f"  Error Rate: {err['error_rate']}")
        if err['unique_errors']:
            print("  Sample Errors:")
            for error in err['unique_errors'][:5]:
                print(f"    - {error}")
        
        # Overall result
        print(f"\n{'='*70}")
        conn_ok = conn['connected'] == report['test_config']['num_clients']
        latency_ok = not report["latency_stats"] or report["latency_stats"]["p99"] < 200
        errors_ok = err['total_errors'] == 0
        
        res = report["resource_usage"]
        cpu_ok = res.get('max_cpu_percent', 100) < 80
        memory_ok = res.get('max_memory_gb', 10) < 2.0
        
        all_ok = conn_ok and latency_ok and errors_ok and cpu_ok and memory_ok
        
        if all_ok:
            print("✓ OVERALL: PASS - All targets met")
        else:
            print("✗ OVERALL: FAIL")
            if not conn_ok:
                print(f"  - Connection drops detected ({conn['disconnected']} clients)")
            if not latency_ok:
                print(f"  - Latency p99 >= 200ms ({report['latency_stats']['p99']:.2f}ms)")
            if not errors_ok:
                print(f"  - Errors detected ({err['total_errors']} errors)")
            if not cpu_ok:
                print(f"  - CPU exceeded 80% (Max: {res.get('max_cpu_percent', 0):.1f}%)")
            if not memory_ok:
                print(f"  - Memory exceeded 2GB (Max: {res.get('max_memory_gb', 0):.2f}GB)")
        print(f"{'='*70}\n")
        
        print(f"Test Duration: {report['test_duration']:.1f}s")


async def broadcast_test_message(base_url: str, endpoint: str, token: str = ""):
    """Send a test broadcast message via the API (if available)."""
    # This would require an API endpoint to trigger broadcasts
    # For now, we rely on natural heartbeats and any existing broadcasts
    pass


def main():
    parser = argparse.ArgumentParser(description="WebSocket Load Test for TopicWebSocketManager")
    parser.add_argument("--clients", type=int, default=100, help="Number of concurrent clients (default: 100)")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds (default: 60)")
    parser.add_argument("--churn", action="store_true", help="Enable connection churn test (clients connect/disconnect)")
    parser.add_argument("--broadcast-rate", type=int, default=0, help="Target broadcast messages per second (0 = natural rate)")
    parser.add_argument("--endpoint", type=str, default="markets", 
                       choices=["markets", "whales", "activities", "brain", "events"],
                       help="WebSocket endpoint to test (default: markets)")
    parser.add_argument("--base-url", type=str, default="ws://localhost:8100",
                       help="Base WebSocket URL (default: ws://localhost:8100)")
    parser.add_argument("--token", type=str, default="",
                       help="Admin API token for authentication")
    parser.add_argument("--output", type=str, default=None,
                       help="Output file for JSON report")
    
    args = parser.parse_args()
    
    # Run load test
    runner = LoadTestRunner(
        num_clients=args.clients,
        endpoint=args.endpoint,
        base_url=args.base_url,
        duration=args.duration,
        token=args.token,
        churn=args.churn,
        broadcast_rate=args.broadcast_rate
    )
    
    report = asyncio.run(runner.run())
    
    # Save report to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {args.output}")


if __name__ == "__main__":
    main()
