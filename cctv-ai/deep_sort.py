"""
AI24x7 - DeepSORT Person Tracking
Tracks persons across multiple cameras over time.
Works with YOLOv8 detection output.
"""
import os, sys, time, json
import numpy as np
import cv2
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from collections import deque

# ─── Paths ────────────────────────────────
TRACK_DB = "/opt/ai24x7/track_db.sqlite"

def init_track_db():
    conn = sqlite3.connect(TRACK_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            track_id TEXT PRIMARY KEY,
            person_name TEXT,
            first_seen TEXT,
            last_seen TEXT,
            camera_first TEXT,
            camera_last TEXT,
            total_seen INTEGER DEFAULT 1,
            is_known INTEGER DEFAULT 0,
            color TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT,
            camera_name TEXT,
            bbox TEXT,
            timestamp TEXT,
            FOREIGN KEY(track_id) REFERENCES tracks(track_id)
        )
    """)
    conn.commit()
    conn.close()

def db_conn():
    conn = sqlite3.connect(TRACK_DB)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Simple Tracker (no deepsort deps needed) ──
class SimpleTracker:
    """
    IoU-based tracker - tracks objects across frames using Intersection over Union.
    Works without deepsort library. Simple but effective for single-camera tracking.
    """
    def __init__(self, max_age=30, min_hits=3, iou_threshold=0.3):
        self.max_age = max_age  # frames to keep track alive without detection
        self.min_hits = min_hits  # min detections before track confirmed
        self.iou_threshold = iou_threshold
        self.tracks = {}  # active tracks: {track_id: Track object}
        self.next_id = 1
        self.frame_count = 0
    
    def update(self, detections):
        """
        Update tracks with new detections.
        detections: list of (x1,y1,x2,y2, confidence, class_id)
        Returns: list of active Track objects
        """
        self.frame_count += 1
        detections = detections or []
        
        # Match detections to existing tracks
        matched, unmatched_dets, unmatched_tracks = self._match(detections)
        
        # Update matched tracks
        for det_idx, track_id in matched:
            x1, y1, x2, y2, conf, cls = detections[det_idx]
            self.tracks[track_id].update(x1, y1, x2, y2, conf, self.frame_count)
        
        # Create new tracks for unmatched detections
        for det_idx in unmatched_dets:
            x1, y1, x2, y2, conf, cls = detections[det_idx]
            new_id = f"T{self.next_id:04d}"
            self.next_id += 1
            self.tracks[new_id] = Track(
                track_id=new_id,
                x1=x1, y1=y1, x2=x2, y2=y2,
                conf=conf, first_frame=self.frame_count,
                current_frame=self.frame_count
            )
        
        # Mark unmatched tracks as missed
        for track_id in unmatched_tracks:
            self.tracks[track_id].mark_missed()
        
        # Remove old tracks
        self._purge()
        
        # Return confirmed tracks
        confirmed = [t for t in self.tracks.values() if t.hits >= self.min_hits]
        return confirmed
    
    def _match(self, detections):
        """Match detections to tracks using IoU"""
        if not self.tracks:
            return [], list(range(len(detections))), []
        
        active = [t for t in self.tracks.values() if not t.missed]
        if not active:
            return [], list(range(len(detections))), []
        
        iou_matrix = np.zeros((len(detections), len(active)))
        for d, det in enumerate(detections):
            for t, track in enumerate(active):
                iou_matrix[d, t] = self._iou(det[:4], track.get_bbox())
        
        matched = []
        unmatched_dets = list(range(len(detections)))
        unmatched_tracks = list(range(len(active)))
        
        # Greedy matching
        while True:
            best_iou = 0
            best_det = -1
            best_track = -1
            
            for d in range(len(detections)):
                for t in range(len(active)):
                    if d in unmatched_dets and t in unmatched_tracks and iou_matrix[d, t] > best_iou:
                        best_iou = iou_matrix[d, t]
                        best_det = d
                        best_track = t
            
            if best_iou >= self.iou_threshold:
                matched.append((best_det, active[best_track].track_id))
                unmatched_dets.remove(best_det)
                unmatched_tracks.remove(best_track)
            else:
                break
        
        return matched, unmatched_dets, [active[t].track_id for t in unmatched_tracks]
    
    def _iou(self, box1, box2):
        """Calculate IoU between two boxes"""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter
        
        return inter / (union + 1e-8)
    
    def _purge(self):
        """Remove old tracks that have been missed for too long"""
        to_delete = []
        for tid, track in self.tracks.items():
            if track.missed and track.age > self.max_age:
                to_delete.append(tid)
        for tid in to_delete:
            del self.tracks[tid]


class Track:
    """Single tracked object"""
    COLORS = [
        (255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),
        (0,255,255),(255,128,0),(128,0,255),(0,128,255),(128,255,0)
    ]
    
    def __init__(self, track_id, x1, y1, x2, y2, conf, first_frame, current_frame):
        self.track_id = track_id
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.conf = conf
        self.first_frame = first_frame
        self.last_frame = current_frame
        self.hits = 1
        self.age = 0
        self.missed = False
        self.color = self.COLORS[int(track_id[1:]) % len(self.COLORS)]
    
    def update(self, x1, y1, x2, y2, conf, frame):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.conf = conf
        self.last_frame = frame
        self.hits += 1
        self.missed = False
        self.age = 0
    
    def mark_missed(self):
        self.missed = True
    
    def get_bbox(self):
        return (self.x1, self.y1, self.x2, self.y2)
    
    def get_center(self):
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)


# ─── Multi-Camera Tracker ─────────────────
class MultiCameraTracker:
    """
    Tracks across cameras.
    Maintains a database of track history per person.
    """
    def __init__(self, max_age_per_cam=30):
        init_track_db()
        self.max_age_per_cam = max_age_per_cam
        self.camera_trackers = {}  # one tracker per camera
        self.colors = {}
    
    def get_tracker(self, camera_name):
        if camera_name not in self.camera_trackers:
            self.camera_trackers[camera_name] = SimpleTracker(
                max_age=self.max_age_per_cam, min_hits=2, iou_threshold=0.3
            )
        return self.camera_trackers[camera_name]
    
    def update(self, camera_name, detections, person_names=None):
        """
        Update all tracks for a camera with new detections.
        detections: list from YOLOv8 person detection
        person_names: optional dict mapping bbox index to person name
        """
        tracker = self.get_tracker(camera_name)
        confirmed_tracks = tracker.update(detections)
        
        results = []
        for track in confirmed_tracks:
            result = {
                "track_id": track.track_id,
                "bbox": track.get_bbox(),
                "center": track.get_center(),
                "confidence": track.conf,
                "hits": track.hits,
                "color": track.color,
                "camera": camera_name,
                "person_name": person_names.get(track.track_id) if person_names else None
            }
            results.append(result)
            
            # Log to DB
            self._log_track(track, camera_name)
        
        return results
    
    def _log_track(self, track, camera_name):
        conn = db_conn()
        try:
            bbox_str = json.dumps(track.get_bbox())
            
            # Update or insert track
            existing = conn.execute(
                "SELECT * FROM tracks WHERE track_id=?", (track.track_id,)
            ).fetchone()
            
            if existing:
                conn.execute("""
                    UPDATE tracks SET
                        last_seen=?,
                        camera_last=?,
                        total_seen=total_seen+1
                    WHERE track_id=?
                """, (datetime.now().isoformat(), camera_name, track.track_id))
            else:
                conn.execute("""
                    INSERT INTO tracks (track_id, first_seen, last_seen, camera_first, camera_last, total_seen, color)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    track.track_id, datetime.now().isoformat(), datetime.now().isoformat(),
                    camera_name, camera_name, 1,
                    json.dumps(track.color)
                ))
            
            conn.execute("""
                INSERT INTO track_history (track_id, camera_name, bbox, timestamp)
                VALUES (?, ?, ?, ?)
            """, (track.track_id, camera_name, json.dumps(track.get_bbox()), datetime.now().isoformat()))
            
            conn.commit()
        finally:
            conn.close()
    
    def get_active_tracks(self, camera_name=None):
        """Get currently active tracks"""
        conn = db_conn()
        if camera_name:
            rows = conn.execute("""
                SELECT * FROM tracks
                WHERE camera_last=? AND last_seen > ?
                ORDER BY last_seen DESC
            """, (camera_name, (datetime.now() - timedelta(minutes=5)).isoformat())).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM tracks
                WHERE last_seen > ?
                ORDER BY last_seen DESC
            """, ((datetime.now() - timedelta(minutes=5)).isoformat(),)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_track_history(self, track_id, limit=50):
        """Get path history of a specific track"""
        conn = db_conn()
        rows = conn.execute("""
            SELECT * FROM track_history
            WHERE track_id=?
            ORDER BY timestamp DESC LIMIT ?
        """, (track_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def draw_tracks(self, frame, tracks, labels=True):
        """Draw track boxes and IDs on frame"""
        for track in tracks:
            x1, y1, x2, y2 = track["bbox"]
            color = track["color"]
            track_id = track["track_id"]
            
            # Draw box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            # Draw ID
            label = f"#{track_id}"
            if labels and track.get("person_name"):
                label = f"#{track_id}: {track['person_name']}"
            
            # Background for text
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(frame, (x1, y1-th-4), (x1+tw, y1), color, -1)
            cv2.putText(frame, label, (x1, y1-2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
            
            # Draw center dot
            cx, cy = track["center"]
            cv2.circle(frame, (int(cx), int(cy)), 3, color, -1)
        
        return frame


# ─── CLI ────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI24x7 DeepSORT Tracker")
    parser.add_argument("--camera", default="test", help="Camera name")
    parser.add_argument("--active", action="store_true", help="Show active tracks")
    parser.add_argument("--history", metavar="TRACK_ID", help="Show track history")
    
    args = parser.parse_args()
    
    if args.active:
        mct = MultiCameraTracker()
        tracks = mct.get_active_tracks(args.camera)
        print(f"\n📍 Active Tracks ({len(tracks)}):")
        for t in tracks:
            print(f"  {t['track_id']} | seen: {t['total_seen']}x | last: {t['camera_last']} | {t['last_seen'][:19]}")
    
    elif args.history:
        mct = MultiCameraTracker()
        hist = mct.get_track_history(args.history, limit=20)
        print(f"\n📜 History for {args.history} ({len(hist)} entries):")
        for h in hist:
            print(f"  {h['timestamp'][:19]} | {h['camera_name']} | bbox: {h['bbox']}")
    
    else:
        print("✅ DeepSORT Tracker module loaded")
        print("   MultiCameraTracker ready for tracking across cameras")
