import os
import json
import time
import hmac
try:
    from flask import Flask, Response, request
except ImportError:
    print("Flask is not installed. Please install it using: pip install Flask")

# মূল ফাইল থেকে ফাংশনগুলো ইমপোর্ট করা হচ্ছে
from sports_events import (
    fetch_all_global_events,
    encrypt_rc4,
    remove_unused_fields,
    HIDE_UNUSED_FIELDS_IN_ENCRYPTED_JSON
)

app = Flask(__name__)

# ===============
# সিকিউরিটি সেটিং
# ================
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
UPDATE_KEY = os.environ.get("UPDATE_KEY", "")
if not ADMIN_KEY:
    print("[WARN] ADMIN_KEY সেট করা নেই")

DECOY_TEXT = (
    "Sports Data Source Mapping\n"
    "--------------------------------\n"
    "Provides structural mapping and network endpoint synchronization for player components."
)

def _key_matches(given: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest((given or "").encode("utf-8"), expected.encode("utf-8"))

def is_admin_request() -> bool:
    return _key_matches(request.args.get("admin", ""), ADMIN_KEY)

def decoy_response():
    resp = Response(DECOY_TEXT, mimetype='text/plain')
    resp.headers['Cache-Control'] = 'no-store'
    return resp

# গ্লোবাল ভ্যারিয়েবল (সার্ভারের মেমোরিতে ডেটা ক্যাশ করে রাখার জন্য)
cache_enc = ""
cache_non_enc = ""
cache_updated_ms = 0
last_update_error = ""

@app.after_request
def add_cors_and_debug_headers(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Expose-Headers'] = 'X-Data-Updated, X-Update-Error, Age, CF-Cache-Status, Date'
    if cache_updated_ms:
        resp.headers['X-Data-Updated'] = str(cache_updated_ms)
    if last_update_error and is_admin_request():
        resp.headers['X-Update-Error'] = last_update_error[:80].encode('ascii', 'ignore').decode().replace('\n', ' ')
    return resp

def perform_update():
    """রিকোয়েস্ট পেলে ডেটা আপডেট করবে"""
    global cache_enc, cache_non_enc, cache_updated_ms, last_update_error
    print("Starting background update for Render...")
    
    try:
        # sports_events থেকে মেইন ফাংশন কল করা হচ্ছে
        events = fetch_all_global_events()
        
        # ============================
        # এডমিন স্ট্যাটিসটিক্স ও লগ তৈরি
        # ============================
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

        mson_injected_links = 0
        sonym3u_injected_links = 0
        tvd_events_injected_links = 0
        for ev in events:
            for s in ev.get("streams", []):
                if s.get("source_type") == "monirul_sonyliv":
                    mson_injected_links += 1
                elif s.get("source_type") == "sonyliv_m3u":
                    sonym3u_injected_links += 1
                elif s.get("source_type") == "tvd_events":
                    tvd_events_injected_links += 1
        
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
                "MonirulSonyLiv_links_injected": mson_injected_links,
                "SonyLivM3U_links_injected": sonym3u_injected_links,
                "TVDekhunEvents_links_injected": tvd_events_injected_links,
                "total_merged_matches": len(merged_details),
                "merge_logs": merged_details
            },
            "events": events
        }
        # ==========================================
        
        # ১. নন-এনক্রিপ্টেড জেসন তৈরি করা (স্ট্যাটিস্টিক্স সহ)
        cache_non_enc = json.dumps(admin_data, indent=2, ensure_ascii=False)
        
        # ২. এনক্রিপ্টেড জেসন  তৈরি করা 
        if HIDE_UNUSED_FIELDS_IN_ENCRYPTED_JSON:
            app_events = remove_unused_fields(events)
        else:
            app_events = events
            
        json_data_enc = json.dumps(app_events, ensure_ascii=False)
        cache_enc = encrypt_rc4(json_data_enc)

        print("Data successfully updated in Render memory.")
        cache_updated_ms = int(time.time() * 1000)
        last_update_error = ""
        
    except Exception as e:
        print(f"Update failed: {e}")
        last_update_error = str(e)

# --- API Routes ---

@app.route('/')
def home():
    return "TVDekhun Sports API is Live!"

@app.route('/update')
def trigger_update():
    """Cron-job.org এই লিংকে প্রতি ৫ মিনিটে হিট করে স্পোর্টস ডাটা আপডেট করবে"""
    if UPDATE_KEY and not _key_matches(request.args.get("key", ""), UPDATE_KEY):
        return decoy_response()
    perform_update()
    resp = Response("Update Process Completed", mimetype='text/plain')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp, 200

# অ্যাডমিনের নন-এনক্রিপ্টেড জেসন
@app.route('/events-for-admin-non-encrypted.json')
def get_admin_events():
    """অ্যাডমিনের জন্য নন-এনক্রিপ্টেড ডেটা"""
    if not is_admin_request():
        return decoy_response()
    if not cache_non_enc:
        perform_update()
    resp = Response(cache_non_enc, mimetype='application/json')
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp

# অ্যাপের ফিক্সড এনক্রিপ্টেড জেসন লিংক
@app.route('/events-latest.json')
def get_encrypted_events_latest():
    if not cache_enc:
        perform_update()
    resp = Response(cache_enc, mimetype='text/plain')
    resp.headers['Cache-Control'] = 'public, max-age=180'
    return resp

# অজানা বা বন্ধ করা যেকোনো লিংকেও একই ডিকয় মেসেজ
@app.errorhandler(404)
def not_found_decoy(e):
    return decoy_response()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
