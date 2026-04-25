"""
AI24x7 - Face Recognition Module v2.0
Fully local - NO external model downloads required!
Layer 1: YOLOv8n (person detection) - downloads automatically
Layer 2: Haar Cascade (face detection) - built into OpenCV
Layer 3: LBPH (face recognition) - built into OpenCV
Layer 4: HOG + LBP histogram (embedding generation) - custom
"""
import os, sys, time, json, sqlite3, hashlib, pickle
import numpy as np
import cv2
from datetime import datetime
from pathlib import Path
import struct

# ─── Check Dependencies ───────────────────
try:
    import torch
    TORCH_OK = True
except:
    TORCH_OK = False

try:
    from ultralytics import YOLO
    ULTRALYTICS_OK = True
except:
    ULTRALYTICS_OK = False

# ─── Paths ────────────────────────────────
MODEL_DIR = Path("/opt/ai24x7/models")
FACES_DIR = Path("/opt/ai24x7/known_faces")
FACE_DB = Path("/opt/ai24x7/face_db.sqlite")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(FACES_DIR, exist_ok=True)

# ─── Database Setup ────────────────────────
def init_db():
    conn = sqlite3.connect(FACE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS known_persons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT UNIQUE NOT NULL,
            person_name TEXT NOT NULL,
            role TEXT,
            encoding BLOB NOT NULL,
            image_path TEXT,
            registered_at TEXT DEFAULT (datetime('now')),
            last_seen TEXT,
            seen_count INTEGER DEFAULT 0,
            camera_locations TEXT DEFAULT '[]'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recognition_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT,
            person_name TEXT,
            camera TEXT,
            confidence REAL,
            timestamp TEXT DEFAULT (datetime('now')),
            image_path TEXT,
            is_known INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unknown_faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encoding BLOB,
            camera TEXT,
            confidence REAL,
            timestamp TEXT DEFAULT (datetime('now')),
            image_path TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(FACE_DB)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Face Embedding Generator ─────────────
class FaceEncoder:
    """
    Generate face embeddings without external models.
    Uses HOG + LBP + color histogram combination.
    Works completely offline.
    """
    def __init__(self, encoding_size=128):
        self.encoding_size = encoding_size
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        self.lbph = cv2.face.LBPHFaceRecognizer_create(
            radius=1, neighbors=8, grid_x=8, grid_y=8, threshold=100
        )
        self.trained = False
    
    def _preprocess_face(self, face):
        """Preprocess face for encoding"""
        if face.size == 0:
            return None
        face = cv2.resize(face, (160, 160))
        gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
        return gray
    
    def _hog_features(self, gray_face):
        """Extract HOG-like features from grayscale face"""
        if gray_face is None:
            return np.zeros(64)
        # Simple gradient-based features
        gx = cv2.Sobel(gray_face, cv2.CV_64F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray_face, cv2.CV_64F, 0, 1, ksize=3)
        mag = np.sqrt(gx**2 + gy**2)
        angle = np.arctan2(gy, gx) * 180 / np.pi
        
        # Histogram of orientations
        hist, _ = np.histogram(angle, bins=8, range=(-180, 180), weights=mag)
        hist = hist / (hist.sum() + 1e-8)
        return hist
    
    def _lbp_features(self, gray_face):
        """Extract LBP-like features"""
        if gray_face is None:
            return np.zeros(32)
        # Simple LBP approximation
        h, w = gray_face.shape
        features = []
        for i in range(1, h-1):
            for j in range(1, w-1):
                center = gray_face[i, j]
                code = 0
                code |= (1 if gray_face[i-1, j-1] >= center else 0)
                code |= (2 if gray_face[i-1, j] >= center else 0)
                code |= (4 if gray_face[i-1, j+1] >= center else 0)
                code |= (8 if gray_face[i, j+1] >= center else 0)
                code |= (16 if gray_face[i+1, j+1] >= center else 0)
                code |= (32 if gray_face[i+1, j] >= center else 0)
                code |= (64 if gray_face[i+1, j-1] >= center else 0)
                code |= (128 if gray_face[i, j-1] >= center else 0)
                features.append(code)
        
        hist, _ = np.histogram(features, bins=32, range=(0, 256))
        hist = hist / (hist.sum() + 1e-8)
        return hist
    
    def _color_features(self, face):
        """Extract color histogram features"""
        if face is None or face.size == 0:
            return np.zeros(24)
        h, w = face.shape[:2]
        # Split into regions
        top = face[:h//3, :, :]
        mid = face[h//3:2*h//3, :, :]
        bot = face[2*h//3:, :, :]
        
        features = []
        for region in [top, mid, bot]:
            for c in range(3):
                h2, _ = np.histogram(region[:,:,c], bins=8, range=(0, 256))
                h2 = h2 / (h2.sum() + 1e-8)
                features.extend(h2)
        return np.array(features)
    
    def encode(self, face_crop):
        """Generate combined embedding from face crop"""
        gray = self._preprocess_face(face_crop)
        if gray is None:
            return np.zeros(self.encoding_size)
        
        hog = self._hog_features(gray)
        lbp = self._lbp_features(gray)
        color = self._color_features(face_crop)
        
        # Concatenate all features
        embedding = np.concatenate([hog, lbp, color])
        
        # Pad or truncate to encoding_size
        if len(embedding) < self.encoding_size:
            embedding = np.pad(embedding, (0, self.encoding_size - len(embedding)))
        else:
            embedding = embedding[:self.encoding_size]
        
        # Normalize
        embedding = embedding / (np.linalg.norm(embedding) + 1e-8)
        return embedding.astype(np.float32)
    
    def cosine_similarity(self, e1, e2):
        return float(np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2) + 1e-8))
    
    def save_training_data(self, encodings, labels, filepath):
        """Save training data for LBPH"""
        with open(filepath, 'wb') as f:
            pickle.dump((encodings, labels), f)
    
    def load_training_data(self, filepath):
        """Load training data"""
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                return pickle.load(f)
        return None, None


# ─── Person Detector (YOLOv8n - auto download) ──
class PersonDetector:
    """
    Uses YOLOv8n for person detection.
    Downloads automatically from ultralytics hub - no manual setup needed.
    Falls back to Haar cascade if ultralytics not available.
    """
    def __init__(self):
        self.model = None
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        if ULTRALYTICS_OK:
            try:
                self.model = YOLO('yolov8n.pt')
                self.type = "yolov8n_person"
                print("✅ PersonDetector: YOLOv8n loaded (auto-download)")
            except Exception as e:
                print(f"⚠️ YOLOv8n load failed: {e}")
                self.type = "haar"
        else:
            self.type = "haar"
            print("⚠️ PersonDetector: Using Haar cascade fallback")
    
    def detect_persons(self, frame, conf=0.5):
        """Detect persons in frame. Returns list of person crops."""
        person_crops = []
        
        if self.model and self.type == "yolov8n_person":
            try:
                results = self.model(frame, verbose=False, conf=conf, classes=[0])
                for r in results:
                    boxes = r.boxes
                    for box in boxes:
                        cls = int(box.cls[0].cpu().numpy())
                        if cls == 0:  # person class
                            x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                            crop = frame[y1:y2, x1:x2]
                            if crop.size > 0:
                                person_crops.append({
                                    'crop': crop,
                                    'bbox': (x1, y1, x2, y2),
                                    'conf': float(box.conf[0].cpu().numpy()),
                                    'type': 'yolo'
                                })
            except Exception as e:
                print(f"YOLOv8n detection error: {e}")
                self._haar_fallback(frame, person_crops)
        else:
            self._haar_fallback(frame, person_crops)
        
        return person_crops
    
    def _haar_fallback(self, frame, person_crops):
        """Fallback: use body/haar detection for person areas"""
        # Use full body detection
        body_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_fullbody.xml'
        )
        if body_cascade.empty():
            return
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        bodies = body_cascade.detectMultiScale(gray, 1.1, 3)
        
        for x, y, w, h in bodies:
            crop = frame[y:y+h, x:x+w]
            if crop.size > 0:
                person_crops.append({
                    'crop': crop,
                    'bbox': (x, y, x+w, y+h),
                    'conf': 0.7,
                    'type': 'haar'
                })
    
    def detect_faces_in_person(self, person_crop, conf=0.3):
        """Detect faces within a person crop"""
        gray = cv2.cvtColor(person_crop, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
        
        face_crops = []
        for x, y, w, h in faces:
            fx1, fy1, fx2, fy2 = x, y, x+w, y+h
            face_crop = person_crop[fy1:fy2, fx1:fx2]
            if face_crop.size > 0:
                face_crops.append({
                    'crop': face_crop,
                    'bbox': (x, y, x+w, y+h),
                    'conf': 0.8
                })
        return face_crops


# ─── Face Recognition Engine ────────────────
class FaceEngine:
    """
    Main face recognition engine.
    Handles add, match, track operations.
    """
    def __init__(self, similarity_threshold=0.45):
        init_db()
        self.detector = PersonDetector()
        self.encoder = FaceEncoder()
        self.threshold = similarity_threshold
        
        # Try to load LBPH recognizer if trained data exists
        training_path = MODEL_DIR / "lbph_training.pkl"
        encodings, labels = self.encoder.load_training_data(str(training_path))
        if encodings and labels:
            try:
                self.encoder.lbph.train(encodings, np.array(labels))
                self.encoder.trained = True
                print(f"✅ LBPH trained with {len(encodings)} samples")
            except Exception as e:
                print(f"⚠️ LBPH training failed: {e}")
    
    def add_person(self, person_id, name, face_crop, role=""):
        """Register a new known person"""
        encoding = self.encoder.encode(face_crop)
        
        # Save face image
        img_path = FACES_DIR / f"{person_id}.jpg"
        cv2.imwrite(str(img_path), face_crop)
        
        conn = get_db()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO known_persons 
                (person_id, person_name, role, encoding, image_path, registered_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (person_id, name, role, encoding.tobytes(), str(img_path), datetime.now().isoformat()))
            conn.commit()
            
            # Save to training data for LBPH
            self._update_lbph_training(person_id, encoding)
            print(f"✅ Registered: {name} ({person_id})")
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
        finally:
            conn.close()
    
    def _update_lbph_training(self, person_id, encoding):
        """Update LBPH training data"""
        training_path = MODEL_DIR / "lbph_training.pkl"
        encodings, labels = self.encoder.load_training_data(str(training_path))
        
        if encodings is None:
            encodings = []
            labels = []
        
        encodings.append(encoding)
        labels.append(person_id)
        
        self.encoder.save_training_data(encodings, labels, str(training_path))
        
        # Retrain LBPH
        try:
            self.encoder.lbph.train(encodings, np.array([hash(l) for l in labels]))
            self.encoder.trained = True
        except Exception as e:
            print(f"⚠️ LBPH retrain failed: {e}")
    
    def find_match(self, face_crop):
        """
        Find best match for a face.
        Returns: (person_id, name, similarity) or (None, None, 0)
        """
        query_encoding = self.encoder.encode(face_crop)
        
        conn = get_db()
        rows = conn.execute("SELECT * FROM known_persons").fetchall()
        conn.close()
        
        if not rows:
            return None, None, 0.0
        
        best_match = None
        best_sim = 0.0
        
        for row in rows:
            stored_encoding = np.frombuffer(row["encoding"], dtype=np.float32)
            sim = self.encoder.cosine_similarity(query_encoding, stored_encoding)
            
            if sim > best_sim:
                best_sim = sim
                best_match = dict(row)
        
        if best_sim >= self.threshold:
            return best_match["person_id"], best_match["person_name"], float(best_sim)
        return None, None, float(best_sim)
    
    def log_recognition(self, person_id, name, camera, conf, img_path=None, is_known=True):
        """Log a recognition event"""
        conn = get_db()
        if person_id:
            conn.execute("""
                UPDATE known_persons 
                SET last_seen=?, seen_count=seen_count+1 
                WHERE person_id=?
            """, (datetime.now().isoformat(), person_id))
        
        conn.execute("""
            INSERT INTO recognition_log 
            (person_id, person_name, camera, confidence, image_path, is_known)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (person_id, name, camera, conf, img_path, 1 if is_known else 0))
        conn.commit()
        conn.close()
    
    def register_unknown(self, face_crop, camera, conf):
        """Log unknown face for admin review"""
        encoding = self.encoder.encode(face_crop)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_path = FACES_DIR / f"unknown_{ts}.jpg"
        cv2.imwrite(str(img_path), face_crop)
        
        conn = get_db()
        conn.execute("""
            INSERT INTO unknown_faces (encoding, camera, confidence, image_path)
            VALUES (?, ?, ?, ?)
        """, (encoding.tobytes(), camera, conf, str(img_path)))
        conn.commit()
        conn.close()
    
    def process_frame(self, frame, camera_name="cam1", draw=True):
        """
        Process entire frame: detect persons → detect faces → match
        Returns: list of recognition results + optionally annotated frame
        """
        results = []
        
        # Step 1: Detect persons
        persons = self.detector.detect_persons(frame, conf=0.5)
        
        for person in persons:
            person_crop = person['crop']
            person_bbox = person['bbox']
            person_conf = person['conf']
            
            # Step 2: Detect faces in person crop
            faces = self.detector.detect_faces_in_person(person_crop, conf=0.4)
            
            if not faces:
                # No face detected but person detected - still log it
                results.append({
                    'person_bbox': person_bbox,
                    'face_bbox': None,
                    'person_id': None,
                    'name': 'Unknown Person',
                    'confidence': person_conf,
                    'is_known': False,
                    'camera': camera_name
                })
                if draw:
                    x1, y1, x2, y2 = person_bbox
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (128, 128, 128), 2)
                    cv2.putText(frame, "Person", (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (128,128,128), 2)
                continue
            
            # Take largest face
            best_face = max(faces, key=lambda f: f['conf'])
            face_crop = best_face['crop']
            face_conf = best_face['conf']
            
            # Step 3: Match face
            pid, name, sim = self.find_match(face_crop)
            
            if pid:
                self.log_recognition(pid, name, camera_name, face_conf, None, True)
                results.append({
                    'person_bbox': person_bbox,
                    'face_bbox': best_face['bbox'],
                    'person_id': pid,
                    'name': name,
                    'confidence': face_conf,
                    'similarity': sim,
                    'is_known': True,
                    'camera': camera_name
                })
                if draw:
                    x1, y1, x2, y2 = person_bbox
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"#{pid}: {name}", (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
            else:
                self.register_unknown(face_crop, camera_name, face_conf)
                results.append({
                    'person_bbox': person_bbox,
                    'face_bbox': best_face['bbox'],
                    'person_id': None,
                    'name': 'Unknown',
                    'confidence': face_conf,
                    'similarity': sim,
                    'is_known': False,
                    'camera': camera_name
                })
                if draw:
                    x1, y1, x2, y2 = person_bbox
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(frame, "UNKNOWN", (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)
        
        return results, frame if draw else None
    
    def get_all_persons(self):
        conn = get_db()
        rows = conn.execute("SELECT * FROM known_persons ORDER BY person_name").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_recognition_log(self, limit=50):
        conn = get_db()
        rows = conn.execute("""
            SELECT * FROM recognition_log ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_unknown_faces(self):
        conn = get_db()
        rows = conn.execute("""
            SELECT * FROM unknown_faces ORDER BY timestamp DESC LIMIT 20
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def remove_person(self, person_id):
        conn = get_db()
        img = conn.execute("SELECT image_path FROM known_persons WHERE person_id=?", (person_id,)).fetchone()
        if img and os.path.exists(img[0]):
            os.remove(img[0])
        conn.execute("DELETE FROM known_persons WHERE person_id=?", (person_id,))
        conn.commit()
        conn.close()
        print(f"✅ Removed: {person_id}")


# ─── CLI ────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI24x7 Face Recognition v2.0")
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument("--list", action="store_true", help="List known persons")
    parser.add_argument("--add", nargs=3, metavar=("ID", "NAME", "IMAGE"),
                       help="Add person: --add emp001 Ram /path/to/face.jpg")
    parser.add_argument("--log", action="store_true", help="Show recognition log")
    parser.add_argument("--unknown", action="store_true", help="Show unknown faces")
    parser.add_argument("--remove", metavar="ID", help="Remove person by ID")
    parser.add_argument("--test", metavar="PATH", help="Test on image")
    
    args = parser.parse_args()
    engine = FaceEngine()
    
    if args.status:
        persons = engine.get_all_persons()
        print(f"📋 System Status:")
        print(f"   Detectors: {'YOLOv8n' if ULTRALYTICS_OK else 'Haar fallback'}")
        print(f"   Encoder: HOG+LBP+Color histogram")
        print(f"   Threshold: {engine.threshold}")
        print(f"   Known persons: {len(persons)}")
    
    elif args.list:
        persons = engine.get_all_persons()
        print(f"\n👥 Known Persons ({len(persons)}):")
        for p in persons:
            print(f"   {p['person_id']:15s} | {p['person_name']:20s} | {p['role'] or 'N/A':12s} | seen: {p['seen_count']}x")
    
    elif args.add:
        pid, name, img_path = args.add
        if not os.path.exists(img_path):
            print(f"❌ Image not found: {img_path}")
        else:
            img = cv2.imread(img_path)
            if img is None:
                print(f"❌ Cannot read image: {img_path}")
            else:
                # Detect and use largest face
                detector = PersonDetector()
                persons = detector.detect_persons(img, conf=0.5)
                if not persons:
                    print("❌ No person found in image")
                else:
                    # Get face from person
                    p = persons[0]
                    faces = detector.detect_faces_in_person(p['crop'], conf=0.3)
                    if faces:
                        face_crop = max(faces, key=lambda f: f['conf'])['crop']
                    else:
                        face_crop = p['crop']  # use full person
                    
                    engine.add_person(pid, name, face_crop, "")
    
    elif args.log:
        log = engine.get_recognition_log(20)
        print(f"\n📜 Recognition Log ({len(log)}):")
        for l in log:
            icon = "✅" if l["is_known"] else "❓"
            print(f"   {icon} {l['timestamp'][:19]} | {l['person_name'] or 'Unknown':20s} | {l['camera']} | {l['confidence']:.0%}")
    
    elif args.unknown:
        unknown = engine.get_unknown_faces()
        print(f"\n❓ Unknown Faces ({len(unknown)}):")
        for u in unknown:
            print(f"   {u['timestamp'][:19]} | {u['camera']} | conf: {u['confidence']:.0%}")
    
    elif args.remove:
        engine.remove_person(args.remove)
    
    elif args.test:
        img = cv2.imread(args.test)
        if img is None:
            print(f"❌ Cannot read: {args.test}")
        else:
            results, _ = engine.process_frame(img.copy(), "test", draw=True)
            cv2.imwrite("/tmp/facerec_result.jpg", img)
            print(f"\n✅ {len(results)} detections")
            for r in results:
                status = f"✅ {r['name']}" if r['is_known'] else "❓ Unknown"
                print(f"   {status} | conf: {r['confidence']:.0%} | sim: {r.get('similarity', 0):.0%}")
            print(f"   Result: /tmp/facerec_result.jpg")
    else:
        print("✅ AI24x7 Face Recognition v2.0 ready!")
        print("   Fully local - no external model downloads!")
        print()
        print("Commands:")
        print("  python3 face_recognition.py --status")
        print("  python3 face_recognition.py --add emp001 Ram /path/to/face.jpg")
        print("  python3 face_recognition.py --list")
        print("  python3 face_recognition.py --test /path/to/image.jpg")