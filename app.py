import os
import json
import time
from datetime import datetime
try:
    from flask import Flask, Response
except ImportError:
    print("Flask is not installed. Please install it using: pip install Flask")

# আপনার মূল ফাইল থেকে ফাংশনগুলো ইমপোর্ট করা হচ্ছে
from sports_events import (
    fetch_all_global_events,
    encrypt_rc4,
    remove_unused_fields,
    HIDE_UNUSED_FIELDS_IN_ENCRYPTED_JSON,
    GMT_PLUS_6
)

app = Flask(__name__)

# গ্লোবাল ভ্যারিয়েবল (সার্ভারের মেমোরিতে ডেটা ক্যাশ করে রাখার জন্য)
cache_enc = ""
cache_non_enc = ""
cache_m3u = ""
cache_updated_ms = 0
last_update_error = ""

@app.after_request
def add_cors_and_debug_headers(resp):
    # এপের WebView (tvdekhun.pages.dev অরিজিন) যেন fetch করতে পারে
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Expose-Headers'] = 'X-Data-Updated, X-Update-Error, Age, CF-Cache-Status, Date'
    if cache_updated_ms:
        resp.headers['X-Data-Updated'] = str(cache_updated_ms)
    if last_update_error:
        resp.headers['X-Update-Error'] = last_update_error[:80].encode('ascii', 'ignore').decode().replace('\n', ' ')
    return resp

def perform_update():
    """এই ফাংশনটি ব্যাকগ্রাউন্ডে বা রিকোয়েস্ট পেলে ডেটা আপডেট করবে"""
    global cache_enc, cache_non_enc, cache_m3u, cache_updated_ms, last_update_error
    print("Starting background update for Render...")
    
    try:
        # sports_events থেকে মেইন ফাংশন কল করা হচ্ছে
        events = fetch_all_global_events()
        
        # ==========================================
        # [নতুন ফিচার] এডমিন স্ট্যাটিসটিক্স ও লগ তৈরি
        # ==========================================
        total_matches = len(events)
        live_matches = sum(1 for ev in events if ev.get("isLive", False))
        
        iptv123_new_matches = sum(1 for ev in events if str(ev.get("id", "")).startswith("iptv123_"))
        
        iptv123_injected_links = 0
        for ev in events:
            if not str(ev.get("id", "")).startswith("iptv123_"):
                for s in ev.get("streams", []):
                    if s.get("source_type") == "iptv123_live":
                        iptv123_injected_links += 1

        bbb_injected_links = 0
        for ev in events:
            for s in ev.get("streams", []):
                if s.get("source_type") == "bbb_json":
                    bbb_injected_links += 1
        
        merged_details = []
        for ev in events:
            alt_titles = ev.get("_alt_titles", [])
            if len(alt_titles) > 1:
                merged_details.append({
                    "final_title": ev.get("title", ""),
                    "merged_titles": alt_titles,
                    "merged_count": len(alt_titles)
                })
                
        admin_data = {
            "___STATISTICS___": {
                "total_matches": total_matches,
                "live_matches": live_matches,
                "iptv123_new_matches_added": iptv123_new_matches,
                "iptv123_links_injected_to_existing": iptv123_injected_links,
                "bbb_links_injected": bbb_injected_links,
                "total_merged_matches": len(merged_details),
                "merge_logs": merged_details
            },
            "events": events
        }
        # ==========================================
        
        # ১. নন-এনক্রিপ্টেড জেসন রেডি করা (স্ট্যাটিস্টিক্স সহ)
        cache_non_enc = json.dumps(admin_data, indent=2, ensure_ascii=False)
        
        # ২. এনক্রিপ্টেড জেসন রেডি করা
        if HIDE_UNUSED_FIELDS_IN_ENCRYPTED_JSON:
            app_events = remove_unused_fields(events)
        else:
            app_events = events
            
        json_data_enc = json.dumps(app_events, ensure_ascii=False)
        cache_enc = encrypt_rc4(json_data_enc)
        
        # ৩. M3U প্লেলিস্ট রেডি করা
        total_m3u_streams = sum(len(ev.get("streams") or []) for ev in events)
        bd_time_str = datetime.now(GMT_PLUS_6).strftime("%Y-%m-%d %I:%M:%S %p")
        m3u_lines = [
            "#EXTM3U",
            "#=================================",
            "#  Developed by: TvDekhun.com",
            "#  Telegram: https://t.me/TvDekhun",
            f"#  Last Updated: {bd_time_str} (BD Time)",
            f"#  Live Channels Count: {total_m3u_streams}",
            "#================================="
        ]
        for ev in events:
            title = ev.get("title", "Unknown Event")
            category = ev.get("category", "Sports")
            poster = ev.get("poster") or ev.get("leagueLogo") or ""
            for s in ev.get("streams") or []:
                server_name = s.get("sourceName", "Unknown Server")
                url = s.get("streamUrl", "")
                headers = s.get("headers", {})
                drm = s.get("drm", {})
                
                m3u_lines.append(f'\n#EXTINF:-1 tvg-logo="{poster}" group-title="{category}", {title} - {server_name}')
                if headers:
                    if "Referer" in headers:
                        m3u_lines.append(f'#EXTVLCOPT:http-referrer={headers["Referer"]}')
                    if "User-Agent" in headers:
                        m3u_lines.append(f'#EXTVLCOPT:http-user-agent={headers["User-Agent"]}')
                if drm and "clearkey" in drm:
                    m3u_lines.append('#KODIPROP:inputstream.adaptive.license_type=clearkey')
                    m3u_lines.append(f'#KODIPROP:inputstream.adaptive.license_key={drm["clearkey"]}')
                m3u_lines.append(url)
                
        cache_m3u = "\n".join(m3u_lines)
        print("✅ Data successfully updated in Render memory.")
        cache_updated_ms = int(time.time() * 1000)
        last_update_error = ""
        
    except Exception as e:
        print(f"❌ Update failed: {e}")
        last_update_error = str(e)

# --- API Routes ---

@app.route('/')
def home():
    return "TVDekhun API is Live! 🚀"

@app.route('/update')
def trigger_update():
    """Cron-job.org এই লিংকে প্রতি ৫ মিনিটে হিট করে ডেটা আপডেট করবে"""
    perform_update()
    resp = Response("Update Process Completed", mimetype='text/plain')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp, 200

# ১. অ্যাডমিনের নন-এনক্রিপ্টেড জেসন
@app.route('/events-for-admin-non-encrypted.json')
def get_admin_events():
    """অ্যাডমিনের জন্য নন-এনক্রিপ্টেড ডেটা"""
    if not cache_non_enc:
        perform_update()
    resp = Response(cache_non_enc, mimetype='application/json')
    resp.headers['Cache-Control'] = 'public, max-age=180'
    return resp

# ২. প্লেয়ারের M3U প্লেলিস্ট
@app.route('/events-for-admin-non-encrypted.m3u')
def get_m3u_playlist():
    """প্লেয়ারের জন্য M3U ডেটা"""
    if not cache_m3u:
        perform_update()
    resp = Response(cache_m3u, mimetype='audio/mpegurl')
    resp.headers['Cache-Control'] = 'public, max-age=180'
    return resp

# ৩. অ্যাপের এনক্রিপ্টেড জেসন (টাইমস্ট্যাম্প সহ ডায়নামিক রাউট)
@app.route('/events-<timestamp>.json')
def get_encrypted_events_with_timestamp(timestamp):
    """
    অ্যাপের জন্য এনক্রিপ্টেড ডেটা।
    লিংকে যেকোনো টাইমস্ট্যাম্প থাকলেও এটি লেটেস্ট ডেটা সার্ভ করবে।
    """
    if not cache_enc:
        perform_update()
    resp = Response(cache_enc, mimetype='text/plain')
    resp.headers['Cache-Control'] = 'public, max-age=180'
    return resp

# ৪. অ্যাপের ফিক্সড লিংক
@app.route('/events-latest.json')
def get_encrypted_events_latest():
    if not cache_enc:
        perform_update()
    resp = Response(cache_enc, mimetype='text/plain')
    resp.headers['Cache-Control'] = 'public, max-age=180'
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
