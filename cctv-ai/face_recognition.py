"""
AI24x7 - Face Recognition Module
YOLOv8-Face detection + ArcFace embeddings for person identification
Runs on customer GPU machine (RTX 3060 minimum)
"""
import os, sys, time, json, sqlite3, hashlib
import numpy as np
import cv2
from datetime import datetime
from pathlib import Path

# ─── Try imports ───────────────────────────
try:
    from ultralytics import YOLO
    ULTRALYTICS_OK = True
except ImportError:
    ULTRALYTICS_OK = False
    print("⚠️ ultralytics not installed - run: pip install ultralytics")

try:
    import onnxruntime as ort
    ONNXRUNTIME_OK = True
except ImportError:
    ONNXRUNTIME_OK = False
    print("⚠️ onnxruntime not installed - pip install onnxruntime onnx")

# ─── Paths ────────────────────────────────
FACE_DB_PATH = "/opt/ai24x7/face_db.sqlite"
FACES_DIR = "/opt/ai24x7/known_faces"
MODEL_DIR = "/opt/ai24x7/models"

os.makedirs(FACES_DIR, exist_ok=True)

# ─── Database Setup ────────────────────────
def init_face_db():
    conn = sqlite3.connect(FACE_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS known_faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT UNIQUE NOT NULL,
            person_name TEXT NOT NULL,
            person_role TEXT,
            embedding BLOB NOT NULL,
            image_path TEXT,
            registered_at TEXT DEFAULT (datetime('now')),
            last_seen TEXT,
            seen_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS face_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT,
            person_name TEXT,
            camera_name TEXT,
            confidence REAL,
            timestamp TEXT DEFAULT (datetime('now')),
            image_path TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unknown_faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            embedding BLOB,
            camera_name TEXT,
            confidence REAL,
            image_path TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

def db_conn():
    conn = sqlite3.connect(FACE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Face Detection (YOLOv8-Face) ─────────
class FaceDetector:
    """
    Uses YOLOv8 face detection model.
    Downloads automatically on first run.
    """
    MODEL_URL = "https://huggingface.co/Bingsu/adetailer/resolve/main/yolov8n-face.pt"
    
    def __init__(self, model_name="yolov8n-face.pt"):
        self.model_name = model_name
        self.model_path = Path(MODEL_DIR) / model_name
        self.model = None
        
        if not ULTRALYTICS_OK:
            print("❌ ultralytics not installed")
            return
        
        # Download if not exists
        if not self.model_path.exists():
            print(f"📥 Downloading YOLOv8n face model...")
            from ultralytics import YOLO
            # Use base yolov8n and configure for face detection
            base_model = YOLO("yolov8n.pt")
            # For now use person detection which is in-built
            self.model = YOLO("yolov8n.pt")
            print("⚠️ Using YOLOv8n (person detection) - for face use yolov8-face model")
        else:
            self.model = YOLO(str(self.model_path))
    
    def detect(self, frame, conf=0.5):
        """
        Detect faces in frame.
        Returns list of bounding boxes: [(x1,y1,x2,y2, confidence), ...]
        """
        if self.model is None:
            # Fallback: detect using face_cascade (OpenCV)
            return self._detect_opencv(frame, conf)
        
        results = self.model(frame, verbose=False, conf=conf)
        detections = []
        
        for r in results:
            boxes = r.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf_score = float(box.conf[0].cpu().numpy())
                cls = int(box.cls[0].cpu().numpy())
                # 0 = person in standard YOLO, adjust as needed
                detections.append((int(x1), int(y1), int(x2), int(y2), conf_score, cls))
        
        return detections
    
    def _detect_opencv(self, frame, conf=0.5):
        """Fallback using OpenCV Haar Cascade"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if os.path.exists(cascade_path):
            cascade = cv2.CascadeClassifier(cascade_path)
            faces = cascade.detectMultiScale(gray, 1.1, 4)
            return [(int(x), int(y), int(x+w), int(y+h), 0.8) for x,y,w,h in faces]
        return []

# ─── Face Embedding (ArcFace) ──────────────
class FaceEmbedder:
    """
    ArcFace embedding generator.
    Uses ONNX model for GPU-accelerated inference.
    """
    def __init__(self, model_path=None):
        self.model_path = model_path or f"{MODEL_DIR}/arcface_w600k_r50.onnx"
        self.session = None
        
        if ONNXRUNTIME_OK and os.path.exists(self.model_path):
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            try:
                self.session = ort.InferenceSession(self.model_path, providers=providers)
                print(f"✅ ArcFace loaded (GPU)")
            except:
                self.session = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
                print(f"✅ ArcFace loaded (CPU)")
        else:
            # Use CLIP/FaceNet alternative - simpler embedding
            print("⚠️ ArcFace model not found - using simplified embeddings")
            self.session = None
    
    def get_embedding(self, face_crop):
        """
        Generate 512-dim embedding for a face crop.
        Returns numpy array of shape (512,)
        """
        if self.session:
            # Preprocess
            face = cv2.resize(face_crop, (112, 112))
            face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
            face = face.astype(np.float32) / 255.0
            face = (face - 0.5) / 0.5
            face = face.transpose(2, 0, 1)[np.newaxis, ...]
            
            # Inference
            input_name = self.session.get_inputs()[0].name
            embedding = self.session.run(None, {input_name: face})[0]
            embedding = embedding.flatten()
            embedding = embedding / np.linalg.norm(embedding)
            return embedding
        else:
            # Fallback: simple histogram embedding
            face = cv2.resize(face_crop, (64, 64))
            gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [128], [0, 256])
            hist = hist.flatten() / hist.sum()
            return hist
    
    def cosine_similarity(self, emb1, emb2):
        """Calculate cosine similarity between two embeddings"""
        return float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2) + 1e-8))

# ─── Face Database Manager ────────────────
class FaceDatabase:
    """
    Manages known face database.
    Handles add, remove, search, match operations.
    """
    def __init__(self):
        init_face_db()
        self.embedder = FaceEmbedder()
        self.threshold = 0.5  # similarity threshold for match
    
    def add_person(self, person_id, person_name, face_crop, person_role=""):
        """
        Add a new known person.
        person_id: unique ID (e.g. "emp_001", "owner")
        person_name: display name
        face_crop: cropped face image (numpy array)
        """
        emb = self.embedder.get_embedding(face_crop)
        emb_bytes = emb.tobytes()
        
        # Save face image
        img_path = f"{FACES_DIR}/{person_id}.jpg"
        cv2.imwrite(img_path, face_crop)
        
        conn = db_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO known_faces 
                (person_id, person_name, person_role, embedding, image_path, registered_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (person_id, person_name, person_role, emb_bytes, img_path, datetime.now().isoformat()))
            conn.commit()
            print(f"✅ Added: {person_name} ({person_id})")
            return True
        except Exception as e:
            print(f"❌ Error adding person: {e}")
            return False
        finally:
            conn.close()
    
    def find_match(self, face_crop, top_k=3):
        """
        Find best match for a detected face.
        Returns: (matched_person_id, name, similarity) or (None, None, 0)
        """
        emb = self.embedder.get_embedding(face_crop)
        conn = db_conn()
        
        try:
            rows = conn.execute("SELECT * FROM known_faces").fetchall()
            if not rows:
                return None, None, 0.0
            
            matches = []
            for row in rows:
                stored_emb = np.frombuffer(row["embedding"], dtype=np.float32)
                sim = self.embedder.cosine_similarity(emb, stored_emb)
                if sim >= self.threshold:
                    matches.append((row["person_id"], row["person_name"], sim))
            
            if not matches:
                return None, None, 0.0
            
            matches.sort(key=lambda x: x[2], reverse=True)
            return matches[0][:3]
        finally:
            conn.close()
    
    def register_unknown(self, face_crop, camera_name, confidence):
        """Log unknown face for later review"""
        emb = self.embedder.get_embedding(face_crop)
        emb_bytes = emb.tobytes()
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_path = f"{FACES_DIR}/unknown_{ts}.jpg"
        cv2.imwrite(img_path, face_crop)
        
        conn = db_conn()
        conn.execute("""
            INSERT INTO unknown_faces (embedding, camera_name, confidence, image_path, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (emb_bytes, camera_name, confidence, img_path, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def log_recognition(self, person_id, person_name, camera_name, confidence, image_path=None):
        """Log successful recognition"""
        conn = db_conn()
        conn.execute("""
            UPDATE known_faces SET last_seen=?, seen_count=seen_count+1 WHERE person_id=?
        """, (datetime.now().isoformat(), person_id))
        conn.execute("""
            INSERT INTO face_log (person_id, person_name, camera_name, confidence, image_path, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (person_id, person_name, camera_name, confidence, image_path, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def get_all_persons(self):
        """Get all registered persons"""
        conn = db_conn()
        rows = conn.execute("SELECT * FROM known_faces ORDER BY person_name").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def remove_person(self, person_id):
        """Remove a person from database"""
        conn = db_conn()
        img_path = conn.execute("SELECT image_path FROM known_faces WHERE person_id=?", (person_id,)).fetchone()
        if img_path and os.path.exists(img_path[0]):
            os.remove(img_path[0])
        conn.execute("DELETE FROM known_faces WHERE person_id=?", (person_id,))
        conn.commit()
        conn.close()
        print(f"✅ Removed: {person_id}")

# ─── Face Recognition Processor ────────────
class FaceProcessor:
    """
    Main processor: detect + recognize faces in CCTV frame.
    """
    def __init__(self):
        self.detector = FaceDetector()
        self.db = FaceDatabase()
        self.confidence_threshold = 0.5
        self.alert_on_unknown = True
        self.alert_on_known = True
    
    def process_frame(self, frame, camera_name="cam1", return_image=False):
        """
        Process a frame: detect faces and match against database.
        Returns: list of recognition results
        """
        detections = self.detector.detect(frame, conf=self.confidence_threshold)
        results = []
        
        for x1, y1, x2, y2, conf, cls in detections:
            face_crop = frame[y1:y2, x1:x2]
            
            if face_crop.size == 0:
                continue
            
            # Find match
            pid, name, sim = self.db.find_match(face_crop)
            
            result = {
                "bbox": (x1, y1, x2, y2),
                "confidence": conf,
                "person_id": pid,
                "person_name": name,
                "similarity": sim,
                "is_known": pid is not None,
                "is_unknown": not pid,
                "camera": camera_name,
                "timestamp": datetime.now().isoformat()
            }
            results.append(result)
            
            # Actions based on result
            if not pid and self.alert_on_unknown:
                self.db.register_unknown(face_crop, camera_name, conf)
                result["action"] = "unknown_face_alert"
            
            elif pid and self.alert_on_known:
                self.db.log_recognition(pid, name, camera_name, conf)
                result["action"] = "known_person_seen"
            
            # Draw on image if requested
            if return_image:
                color = (0, 255, 0) if pid else (0, 0, 255)
                label = f"{name} ({sim:.0%})" if pid else f"Unknown ({conf:.0%})"
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        
        return results
    
    def add_known_person(self, person_id, name, face_image, role=""):
        """Register a new known person"""
        return self.db.add_person(person_id, name, face_image, role)
    
    def get_recognition_log(self, limit=50):
        """Get recent recognition history"""
        conn = db_conn()
        rows = conn.execute("""
            SELECT * FROM face_log ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_unknown_faces(self):
        """Get unknown faces for admin review"""
        conn = db_conn()
        rows = conn.execute("""
            SELECT id, camera_name, confidence, image_path, timestamp
            FROM unknown_faces ORDER BY timestamp DESC LIMIT 20
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ─── CLI ────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI24x7 Face Recognition")
    parser.add_argument("--add", metavar=("ID", "NAME"), nargs=2, help="Add known person")
    parser.add_argument("--list", action="store_true", help="List known persons")
    parser.add_argument("--log", action="store_true", help="Show recognition log")
    parser.add_argument("--unknown", action="store_true", help="Show unknown faces")
    parser.add_argument("--remove", metavar="ID", help="Remove person")
    parser.add_argument("--test-image", metavar="PATH", help="Test on image file")
    
    args = parser.parse_args()
    fp = FaceProcessor()
    
    if args.list:
        persons = fp.db.get_all_persons()
        print(f"\n📋 Known Persons ({len(persons)}):")
        for p in persons:
            print(f"  {p['person_id']:15s} | {p['person_name']:20s} | {p['person_role'] or 'N/A':15s} | seen: {p['seen_count']}x")
    
    elif args.add:
        pid, name = args.add
        print(f"📸 Taking photo for {name}...")
        print("⚠️ Use --test-image with a cropped face image for now")
        print(f"   Then: python3 face_recognition.py --enroll {pid} {name} <image_path>")
    
    elif args.log:
        log = fp.get_recognition_log(20)
        print(f"\n📜 Recent Recognitions ({len(log)}):")
        for l in log:
            known = "✅" if l["person_id"] else "❓"
            print(f"  {known} {l['timestamp'][:19]} | {l['person_name'] or 'Unknown':20s} | {l['camera']} | {l['confidence']:.0%}")
    
    elif args.unknown:
        unknown = fp.get_unknown_faces()
        print(f"\n❓ Unknown Faces ({len(unknown)}):")
        for u in unknown:
            print(f"  {u['timestamp'][:19]} | {u['camera']} | conf: {u['confidence']:.0%} | img: {u['image_path']}")
    
    elif args.remove:
        fp.db.remove_person(args.remove)
    
    elif args.test_image:
        img = cv2.imread(args.test_image)
        if img is None:
            print(f"❌ Cannot read image: {args.test_image}")
        else:
            results = fp.process_frame(img, "test_cam", return_image=True)
            cv2.imwrite("/tmp/face_result.jpg", img)
            print(f"\n✅ Detected {len(results)} face(s)")
            for r in results:
                status = f"✅ {r['person_name']}" if r['is_known'] else "❓ Unknown"
                print(f"  {status} | sim: {r['similarity']:.0%} | conf: {r['confidence']:.0%}")
            print(f"  Result image saved: /tmp/face_result.jpg")
    
    else:
        parser.print_help()
