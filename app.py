"""
MLBB Account Checker API Server
Complete version with all features
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import threading
import time
import os
import json
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
import traceback

# Import from checker
from checker import (
    check_accounts_bulk,
    fetch_cn31_token,
    fetch_cn31_token_with_server,
    solve_acw_sc_v2,
    cookie_manager,
    load_device_manager,
    device_manager,
    get_player_info_api,
    save_detailed_account_api,
    Colors,
    HAS_INFO,
    HAS_CURL_CFFI,
    CN31Manager,
    CN31_SERVERS,
    check_account_with_retry,
    process_single_account
)

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store active tasks
tasks = {}
task_lock = threading.Lock()

# Initialize device manager
load_device_manager()

# ============ Task Classes ============

class CheckerTask:
    def __init__(self, task_id: str, accounts: List[str], threads: int = 10, detailed: bool = False):
        self.task_id = task_id
        self.accounts = accounts
        self.threads = threads
        self.detailed = detailed
        self.status = "pending"  # pending, running, completed, failed, cancelled
        self.progress = 0
        self.total = len(accounts)
        self.results = []
        self.valid = 0
        self.invalid = 0
        self.errors = []
        self.start_time = None
        self.end_time = None
        self.valid_accounts = []
        self.session_accounts = []
        self.detailed_accounts = []
        self.valid_detailed_count = 0
        
        # Collector tier stats
        self.collector_stats = {
            "No Tier": 0,
            "Amateur Collector": 0,
            "Junior Collector": 0,
            "Seasoned Collector": 0,
            "Expert Collector": 0,
            "Renowned Collector": 0,
            "Exalted Collector": 0,
            "Mega Collector": 0,
            "World Collector": 0
        }
        
        # Rank stats
        self.rank_stats = {
            "Warrior": 0,
            "Elite": 0,
            "Master": 0,
            "Grandmaster": 0,
            "Epic": 0,
            "Legend": 0,
            "Mythic": 0,
            "Mythical Honor": 0,
            "Mythical Glory": 0,
            "Mythical Immortal": 0
        }
        
        # Skin stats
        self.skin_stats = {
            "Common": 0,
            "Exceptional": 0,
            "Deluxe": 0,
            "Exquisite": 0,
            "Grand": 0,
            "Supreme": 0,
            "Total": 0
        }
    
    def to_dict(self):
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "valid": self.valid,
            "invalid": self.invalid,
            "valid_detailed": self.valid_detailed_count,
            "errors": self.errors[:10],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.end_time - self.start_time if self.start_time and self.end_time else None,
            "valid_accounts": self.valid_accounts[:20],
            "session_accounts": self.session_accounts[:20],
            "detailed_accounts": self.detailed_accounts[:10],
            "collector_stats": self.collector_stats,
            "rank_stats": self.rank_stats,
            "skin_stats": self.skin_stats
        }

def process_task(task: CheckerTask):
    """Process a checker task in background"""
    try:
        task.status = "running"
        task.start_time = time.time()
        
        # Create callback for progress updates
        def progress_callback(result):
            with task_lock:
                task.progress += 1
                task.results.append(result)
                
                if result.get("success"):
                    task.valid += 1
                    acc_data = result.get("account_data", {})
                    email = acc_data.get("email", "unknown")
                    task.valid_accounts.append(email)
                    
                    if acc_data.get("session"):
                        task.session_accounts.append(email)
                    
                    # Check for player info
                    player_data = result.get("player_data")
                    if player_data and task.detailed:
                        task.valid_detailed_count += 1
                        
                        # Get basic info
                        d = player_data.get("data", {})
                        basic = d.get("basic_info", {})
                        game = d.get("game_info", {})
                        collector = d.get("collector_info", {})
                        skin = d.get("skin_info", {})
                        
                        # Record collector tier
                        collector_tier = collector.get("collector_tier", "No Tier")
                        if collector_tier in task.collector_stats:
                            task.collector_stats[collector_tier] += 1
                        else:
                            task.collector_stats["No Tier"] += 1
                        
                        # Record rank
                        rank = game.get("current_rank", "Unknown")
                        for rank_type in task.rank_stats:
                            if rank_type in rank:
                                task.rank_stats[rank_type] += 1
                                break
                        
                        # Record skin stats
                        skin_breakdown = skin.get("skin_breakdown", {})
                        for skin_type, count in skin_breakdown.items():
                            if skin_type == "Total Skins":
                                task.skin_stats["Total"] += count
                            elif "Common" in skin_type:
                                task.skin_stats["Common"] += count
                            elif "Exceptional" in skin_type:
                                task.skin_stats["Exceptional"] += count
                            elif "Deluxe" in skin_type:
                                task.skin_stats["Deluxe"] += count
                            elif "Exquisite" in skin_type:
                                task.skin_stats["Exquisite"] += count
                            elif "Grand" in skin_type:
                                task.skin_stats["Grand"] += count
                            elif "Supreme" in skin_type:
                                task.skin_stats["Supreme"] += count
                        
                        # Add to detailed accounts
                        task.detailed_accounts.append({
                            "email": email,
                            "nickname": basic.get("nickname", "Unknown"),
                            "player_id": basic.get("player_id", "Unknown"),
                            "server": basic.get("server", "Unknown"),
                            "level": basic.get("level", 0),
                            "skin_count": basic.get("skin_count", 0),
                            "hero_count": basic.get("hero_count", 0),
                            "current_rank": rank,
                            "high_rank": game.get("high_rank", "Unknown"),
                            "collector_tier": collector_tier,
                            "collector_point": collector.get("collector_point", 0),
                            "location": d.get("location_info", {}).get("location", "Unknown"),
                            "last_login": d.get("location_info", {}).get("last_login", "Never"),
                            "achievement_points": game.get("achievement_points", 0),
                            "total_matches": game.get("matches", 0),
                            "hero_history": game.get("hero_history", [])[:5]
                        })
                else:
                    task.invalid += 1
                    if result.get("error"):
                        task.errors.append(result.get("error"))
        
        # Run the checker
        result = check_accounts_bulk(
            accounts=task.accounts,
            threads=task.threads,
            callback=progress_callback,
            detailed=task.detailed,
            task_id=task.task_id
        )
        
        task.status = "completed" if result.get("success") else "failed"
        task.end_time = time.time()
        
        logger.info(f"Task {task.task_id} completed: {task.valid} valid, {task.invalid} invalid")
        
    except Exception as e:
        task.status = "failed"
        task.errors.append(str(e))
        task.end_time = time.time()
        logger.error(f"Task {task.task_id} failed: {e}")
        traceback.print_exc()

# ============ API Routes ============

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "timestamp": time.time(),
        "device_count": len(device_manager.devices) if device_manager else 0,
        "has_info": HAS_INFO,
        "has_curl_cffi": HAS_CURL_CFFI,
        "cn31_servers": len(CN31_SERVERS)
    })

@app.route('/api/check', methods=['POST'])
def check_accounts():
    """
    Check accounts endpoint
    
    Request body:
    {
        "accounts": ["email:pass", "email2:pass2"],
        "threads": 10,
        "async": true,
        "detailed": true,
        "callback_url": "https://your-webhook.com/callback"  # optional
    }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Missing request body"}), 400
    
    if "accounts" not in data:
        return jsonify({"error": "Missing accounts parameter"}), 400
    
    accounts = data.get("accounts", [])
    threads = min(int(data.get("threads", 10)), 30)
    async_mode = data.get("async", True)
    detailed = data.get("detailed", True)
    callback_url = data.get("callback_url")
    
    if not accounts:
        return jsonify({"error": "No accounts provided"}), 400
    
    # Filter valid accounts
    valid_accounts = [acc for acc in accounts if ":" in acc]
    
    if not valid_accounts:
        return jsonify({"error": "No valid accounts found (format: email:pass)"}), 400
    
    # Get CN31 token first
    token, server = fetch_cn31_token_with_server()
    if not token:
        return jsonify({"error": "Failed to get CN31 token"}), 503
    
    # Create task
    task_id = f"task_{int(time.time())}_{hash(str(valid_accounts)) % 10000}"
    task = CheckerTask(task_id, valid_accounts, threads, detailed)
    
    with task_lock:
        tasks[task_id] = task
    
    if async_mode:
        # Run in background
        thread = threading.Thread(target=process_task, args=(task,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "task_id": task_id,
            "status": "started",
            "total": len(valid_accounts),
            "message": "Check running in background. Use GET /api/task/<task_id> to check status",
            "endpoints": {
                "status": f"/api/task/{task_id}",
                "results": f"/api/task/{task_id}/results",
                "full_results": f"/api/task/{task_id}/full_results",
                "download": f"/api/task/{task_id}/download",
                "cancel": f"/api/task/{task_id}/cancel"
            }
        })
    else:
        # Sync mode - wait for completion
        process_task(task)
        return jsonify(task.to_dict())

@app.route('/api/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    with task_lock:
        task = tasks.get(task_id)
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    return jsonify(task.to_dict())

@app.route('/api/task/<task_id>/results', methods=['GET'])
def get_task_results(task_id):
    with task_lock:
        task = tasks.get(task_id)
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    if task.status not in ["completed", "failed"]:
        return jsonify({"error": f"Task not completed yet. Status: {task.status}"}), 400
    
    # Full results
    return jsonify({
        "task_id": task_id,
        "status": task.status,
        "total": task.total,
        "valid": task.valid,
        "invalid": task.invalid,
        "valid_detailed": task.valid_detailed_count,
        "duration": task.end_time - task.start_time if task.start_time and task.end_time else None,
        "valid_accounts": task.valid_accounts,
        "session_accounts": task.session_accounts,
        "detailed_accounts": task.detailed_accounts,
        "collector_stats": task.collector_stats,
        "rank_stats": task.rank_stats,
        "skin_stats": task.skin_stats,
        "errors": task.errors[:20],
        "all_results": task.results[:50]
    })

@app.route('/api/task/<task_id>/full_results', methods=['GET'])
def get_task_full_results(task_id):
    """Get all results including full player info"""
    with task_lock:
        task = tasks.get(task_id)
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    if task.status not in ["completed", "failed"]:
        return jsonify({"error": f"Task not completed yet. Status: {task.status}"}), 400
    
    # Prepare response with all results
    full_results = []
    for r in task.results:
        if r.get("success") and r.get("player_data"):
            full_results.append({
                "account": r.get("account"),
                "success": True,
                "player_info": r.get("player_data")
            })
        else:
            full_results.append({
                "account": r.get("account"),
                "success": r.get("success", False),
                "error": r.get("error")
            })
    
    return jsonify({
        "task_id": task_id,
        "total": task.total,
        "valid": task.valid,
        "invalid": task.invalid,
        "valid_detailed": task.valid_detailed_count,
        "results": full_results
    })

@app.route('/api/task/<task_id>/cancel', methods=['POST'])
def cancel_task(task_id):
    with task_lock:
        task = tasks.get(task_id)
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    if task.status in ["completed", "failed"]:
        return jsonify({"error": f"Task already {task.status}"}), 400
    
    task.status = "cancelled"
    task.end_time = time.time()
    
    return jsonify({
        "message": "Task cancelled",
        "task_id": task_id
    })

@app.route('/api/task/<task_id>/download', methods=['GET'])
def download_task_results(task_id):
    """Download results as a file"""
    with task_lock:
        task = tasks.get(task_id)
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    if task.status not in ["completed", "failed"]:
        return jsonify({"error": f"Task not completed yet. Status: {task.status}"}), 400
    
    # Generate text file content
    content = []
    content.append("=" * 70)
    content.append(f"MLBB ACCOUNT CHECK RESULTS")
    content.append(f"Task ID: {task_id}")
    content.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    content.append(f"Total: {task.total} | Valid: {task.valid} | Invalid: {task.invalid}")
    content.append("=" * 70)
    content.append("")
    
    content.append("VALID ACCOUNTS:")
    content.append("-" * 50)
    for acc in task.valid_accounts:
        content.append(f"  {acc}")
    
    content.append("")
    content.append("DETAILED ACCOUNTS:")
    content.append("-" * 50)
    for acc in task.detailed_accounts:
        content.append(f"  Email: {acc.get('email')}")
        content.append(f"  Nickname: {acc.get('nickname')}")
        content.append(f"  Player ID: {acc.get('player_id')}")
        content.append(f"  Server: {acc.get('server')}")
        content.append(f"  Level: {acc.get('level')}")
        content.append(f"  Skin Count: {acc.get('skin_count')}")
        content.append(f"  Hero Count: {acc.get('hero_count')}")
        content.append(f"  Rank: {acc.get('current_rank')}")
        content.append(f"  Highest Rank: {acc.get('high_rank')}")
        content.append(f"  Collector Tier: {acc.get('collector_tier')}")
        content.append(f"  Collector Points: {acc.get('collector_point')}")
        content.append(f"  Location: {acc.get('location')}")
        content.append(f"  Last Login: {acc.get('last_login')}")
        content.append(f"  Achievement Points: {acc.get('achievement_points')}")
        content.append(f"  Total Matches: {acc.get('total_matches')}")
        if acc.get('hero_history'):
            content.append(f"  Hero History: {', '.join(acc.get('hero_history'))}")
        content.append("-" * 30)
    
    content.append("")
    content.append("COLLECTOR STATS:")
    content.append("-" * 50)
    for tier, count in task.collector_stats.items():
        if count > 0:
            content.append(f"  {tier}: {count}")
    
    content.append("")
    content.append("RANK STATS:")
    content.append("-" * 50)
    for rank, count in task.rank_stats.items():
        if count > 0:
            content.append(f"  {rank}: {count}")
    
    content.append("")
    content.append("SKIN STATS:")
    content.append("-" * 50)
    for skin_type, count in task.skin_stats.items():
        if count > 0:
            content.append(f"  {skin_type}: {count}")
    
    content.append("")
    content.append("=" * 70)
    
    return Response(
        "\n".join(content),
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment;filename=results_{task_id}.txt"}
    )

@app.route('/api/cn31', methods=['GET'])
def get_cn31_token():
    token, server = fetch_cn31_token_with_server()
    if token:
        return jsonify({
            "token": token,
            "server": server,
            "expires_in": 300
        })
    return jsonify({"error": "Failed to get CN31 token"}), 503

@app.route('/api/cn31/servers', methods=['GET'])
def get_cn31_servers():
    cn31_manager = CN31Manager()
    stats = cn31_manager.get_stats()
    return jsonify({
        "servers": stats,
        "total": len(stats)
    })

@app.route('/api/waf/solve', methods=['POST'])
def solve_waf():
    data = request.get_json()
    html = data.get("html", "")
    
    if not html:
        return jsonify({"error": "Missing html parameter"}), 400
    
    result = solve_acw_sc_v2(html)
    if result:
        return jsonify({
            "acw_sc__v2": result,
            "solved": True
        })
    return jsonify({"error": "Failed to solve WAF"}), 503

@app.route('/api/waf/check', methods=['POST'])
def check_waf():
    """Check if response contains WAF challenge"""
    data = request.get_json()
    html = data.get("html", "")
    
    if not html:
        return jsonify({"error": "Missing html parameter"}), 400
    
    from checker import is_waf_challenge
    
    # Create mock response object
    class MockResponse:
        def __init__(self, text):
            self.text = text
            self.status_code = 200
    
    resp = MockResponse(html)
    has_waf = is_waf_challenge(resp)
    
    return jsonify({
        "has_waf": has_waf,
        "html_length": len(html)
    })

@app.route('/api/stats', methods=['GET'])
def get_stats():
    with task_lock:
        running = 0
        completed = 0
        pending = 0
        failed = 0
        cancelled = 0
        total_valid = 0
        total_invalid = 0
        
        for t in tasks.values():
            if t.status == "running":
                running += 1
            elif t.status == "completed":
                completed += 1
                total_valid += t.valid
                total_invalid += t.invalid
            elif t.status == "failed":
                failed += 1
            elif t.status == "cancelled":
                cancelled += 1
            else:
                pending += 1
        
        # Get recent tasks
        recent_tasks = []
        for task_id in list(tasks.keys())[-10:]:
            t = tasks[task_id]
            recent_tasks.append({
                "task_id": task_id,
                "status": t.status,
                "progress": t.progress,
                "total": t.total,
                "valid": t.valid,
                "invalid": t.invalid
            })
        
        return jsonify({
            "total_tasks": len(tasks),
            "running": running,
            "completed": completed,
            "pending": pending,
            "failed": failed,
            "cancelled": cancelled,
            "total_valid": total_valid,
            "total_invalid": total_invalid,
            "device_count": len(device_manager.devices) if device_manager else 0,
            "has_info": HAS_INFO,
            "has_curl_cffi": HAS_CURL_CFFI,
            "recent_tasks": recent_tasks
        })

@app.route('/api/devices', methods=['GET'])
def get_devices():
    if device_manager:
        return jsonify({
            "total": len(device_manager.devices),
            "devices": device_manager.devices[:50],
            "failed_count": len(device_manager.failed_devices),
            "device_usage": dict(list(device_manager.device_usage.items())[:20])
        })
    return jsonify({"error": "Device manager not initialized"}), 503

@app.route('/api/devices/reload', methods=['POST'])
def reload_devices():
    load_device_manager()
    return jsonify({
        "message": "Devices reloaded",
        "device_count": len(device_manager.devices) if device_manager else 0
    })

@app.route('/api/clear_tasks', methods=['POST'])
def clear_tasks():
    """Clear completed/failed tasks older than 1 hour"""
    with task_lock:
        current_time = time.time()
        to_remove = []
        for task_id, task in tasks.items():
            if task.status in ["completed", "failed", "cancelled"] and task.end_time and (current_time - task.end_time > 3600):
                to_remove.append(task_id)
        
        for task_id in to_remove:
            del tasks[task_id]
        
        return jsonify({
            "cleared": len(to_remove),
            "remaining": len(tasks)
        })

@app.route('/api/clear_all_tasks', methods=['POST'])
def clear_all_tasks():
    """Clear all completed/failed tasks"""
    with task_lock:
        to_remove = []
        for task_id, task in tasks.items():
            if task.status in ["completed", "failed", "cancelled"]:
                to_remove.append(task_id)
        
        for task_id in to_remove:
            del tasks[task_id]
        
        return jsonify({
            "cleared": len(to_remove),
            "remaining": len(tasks)
        })

@app.route('/api/cookies', methods=['GET'])
def get_cookies():
    cookies = cookie_manager.get_cookies()
    return jsonify({
        "cookies": cookies,
        "last_refresh": cookie_manager.last_refresh
    })

@app.route('/api/cookies/refresh', methods=['POST'])
def refresh_cookies():
    proxy = get_proxy() if 'get_proxy' in dir() else None
    result = cookie_manager.force_refresh(proxy)
    return jsonify({
        "success": result,
        "cookies": cookie_manager.cookies
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)