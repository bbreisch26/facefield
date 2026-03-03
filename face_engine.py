from pathlib import Path
from typing import Dict, List
from uuid import uuid4

import numpy as np
from insightface.app import FaceAnalysis
from PIL import Image

# Required by spec: initialize globally at startup.
app = FaceAnalysis()
app.prepare(ctx_id=0, det_size=(640, 640))


def process_image(image_path: str) -> List[Dict]:
    image = Image.open(image_path).convert("RGB")
    np_img = np.array(image)

    detected_faces = app.get(np_img)
    results: List[Dict] = []

    for face in detected_faces:
        x1, y1, x2, y2 = [int(v) for v in face.bbox]

        # Clamp bbox to valid image bounds.
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(np_img.shape[1], x2)
        y2 = min(np_img.shape[0], y2)

        if x2 <= x1 or y2 <= y1:
            continue

        crop = image.crop((x1, y1, x2, y2))
        face_filename = f"{uuid4().hex}.jpg"
        face_output_path = Path("faces") / face_filename
        crop.save(face_output_path)

        results.append(
            {
                "embedding": np.array(face.embedding, dtype=np.float32),
                "bbox": (x1, y1, x2, y2),
                "face_crop_path": face_filename,
            }
        )

    return results
