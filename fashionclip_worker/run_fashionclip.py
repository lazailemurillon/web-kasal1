import os
import json
import gc
import numpy as np

from PIL import Image
from fashion_clip.fashion_clip import FashionCLIP


MEDIA_DIR = "media/gowns"
OUTPUT_FILE = "fashionclip_worker/gown_embeddings.json"


def normalize_embedding(embedding):
    embedding = np.asarray(embedding, dtype=np.float32)

    norm = np.linalg.norm(embedding)

    if norm == 0:
        return embedding

    return embedding / norm


def get_color_histogram(image):
    image = image.convert("RGB")
    image = image.resize((64, 64))

    image_array = np.asarray(image, dtype=np.uint8)

    bins = 8

    r = image_array[:, :, 0] // 32
    g = image_array[:, :, 1] // 32
    b = image_array[:, :, 2] // 32

    histogram = r * bins * bins + g * bins + b

    result = np.zeros(bins * bins * bins, dtype=np.float32)

    np.add.at(result, histogram.reshape(-1), 1)

    total = result.sum()

    if total > 0:
        result /= total

    return result


print("Loading FashionCLIP...")

fclip = FashionCLIP("fashion-clip")

print("FashionCLIP loaded.")


results = {}

image_files = []

for filename in os.listdir(MEDIA_DIR):

    filepath = os.path.join(MEDIA_DIR, filename)

    if os.path.isfile(filepath):

        lower = filename.lower()

        if lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
            image_files.append(filename)


print(f"Found {len(image_files)} gown images.")


for index, filename in enumerate(image_files, start=1):

    filepath = os.path.join(MEDIA_DIR, filename)

    print(f"Processing {index}/{len(image_files)}: {filename}")

    try:

        image = Image.open(filepath).convert("RGB")

        embedding = fclip.encode_images(
            [image],
            batch_size=1
        )[0]

        embedding = normalize_embedding(embedding)

        color = get_color_histogram(image)

        results[filename] = {
            "embedding": embedding.tolist(),
            "color": color.tolist(),
        }

        del image
        del embedding
        del color

        gc.collect()

    except Exception as e:

        print(f"ERROR processing {filename}: {e}")


os.makedirs(
    os.path.dirname(OUTPUT_FILE),
    exist_ok=True
)


with open(OUTPUT_FILE, "w", encoding="utf-8") as f:

    json.dump(
        results,
        f
    )


print("Finished.")

print(f"Saved embeddings to: {OUTPUT_FILE}")

print(f"Successfully processed: {len(results)} images.")