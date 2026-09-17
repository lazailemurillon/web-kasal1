import os
import json
import gc
import numpy as np

from PIL import Image
from fashion_clip.fashion_clip import FashionCLIP


MEDIA_DIR = "media/gowns"
OUTPUT_FILE = "fashionclip_worker/fashion_results.json"


# ============================================================
# HELPERS
# ============================================================

def normalize_embedding(embedding):
    embedding = np.asarray(
        embedding,
        dtype=np.float32
    )

    norm = np.linalg.norm(embedding)

    if norm == 0:
        return embedding

    return embedding / norm


def cosine_similarity(vector_a, vector_b):
    norm_a = np.linalg.norm(vector_a)
    norm_b = np.linalg.norm(vector_b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(
        np.dot(vector_a, vector_b)
        / (norm_a * norm_b)
    )


# ============================================================
# COLOR HISTOGRAM
# ============================================================

def get_color_histogram(image):
    image = image.convert("RGB")
    image = image.resize((64, 64))

    image_array = np.asarray(
        image,
        dtype=np.float32
    )

    rgb = image_array / 255.0

    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]

    maximum = np.max(rgb, axis=2)
    minimum = np.min(rgb, axis=2)

    difference = maximum - minimum

    hue = np.zeros_like(maximum)

    mask = difference != 0

    mask_r = mask & (maximum == r)

    hue[mask_r] = (
        60 *
        ((g[mask_r] - b[mask_r]) /
         difference[mask_r])
    ) % 360

    mask_g = mask & (maximum == g)

    hue[mask_g] = (
        60 *
        ((b[mask_g] - r[mask_g]) /
         difference[mask_g])
        + 120
    ) % 360

    mask_b = mask & (maximum == b)

    hue[mask_b] = (
        60 *
        ((r[mask_b] - g[mask_b]) /
         difference[mask_b])
        + 240
    ) % 360

    saturation = np.zeros_like(maximum)

    nonzero_max = maximum != 0

    saturation[nonzero_max] = (
        difference[nonzero_max]
        /
        maximum[nonzero_max]
    )

    hue_bins = 18
    saturation_bins = 5
    value_bins = 5

    hue_index = np.minimum(
        (hue / 360 * hue_bins).astype(np.int8),
        hue_bins - 1
    )

    saturation_index = np.minimum(
        (saturation * saturation_bins).astype(np.int8),
        saturation_bins - 1
    )

    value_index = np.minimum(
        (maximum * value_bins).astype(np.int8),
        value_bins - 1
    )

    histogram = np.zeros(
        (
            hue_bins,
            saturation_bins,
            value_bins
        ),
        dtype=np.float32
    )

    for h, s, v in zip(
        hue_index.flat,
        saturation_index.flat,
        value_index.flat
    ):
        histogram[h, s, v] += 1

    total = histogram.sum()

    if total > 0:
        histogram /= total

    return histogram.ravel()


def color_similarity(color_a, color_b):
    return float(
        np.minimum(
            color_a,
            color_b
        ).sum()
    )


# ============================================================
# LOAD FASHIONCLIP
# ============================================================

print("=" * 70)
print("STARTING FASHIONCLIP")
print("=" * 70)

fclip = FashionCLIP("fashion-clip")

print("=" * 70)
print("FASHIONCLIP LOADED")
print("=" * 70)


# ============================================================
# FIND UPLOADED PHOTO
# ============================================================

photo_path = os.environ.get("PHOTO_PATH")

if not photo_path:
    raise RuntimeError(
        "PHOTO_PATH environment variable was not provided."
    )

if not os.path.exists(photo_path):
    raise FileNotFoundError(
        f"Uploaded photo not found: {photo_path}"
    )

print("Uploaded photo:")
print(photo_path)


# ============================================================
# QUERY IMAGE
# ============================================================

query_image = Image.open(
    photo_path
).convert("RGB")

query_embedding = fclip.encode_images(
    [query_image],
    batch_size=1
)[0]

query_embedding = normalize_embedding(
    query_embedding
)

query_color = get_color_histogram(
    query_image
)

del query_image

gc.collect()


# ============================================================
# FIND GOWN IMAGES
# ============================================================

image_files = []

for filename in os.listdir(MEDIA_DIR):

    filepath = os.path.join(
        MEDIA_DIR,
        filename
    )

    if not os.path.isfile(filepath):
        continue

    if filename.lower().endswith(
        (".jpg", ".jpeg", ".png", ".webp")
    ):
        image_files.append(filename)


print(
    f"Found {len(image_files)} gown images."
)


# ============================================================
# COMPARE GOWNS
# ============================================================

results = []

for index, filename in enumerate(
    image_files,
    start=1
):

    filepath = os.path.join(
        MEDIA_DIR,
        filename
    )

    print(
        f"Processing gown "
        f"{index}/{len(image_files)}: "
        f"{filename}"
    )

    try:

        gown_image = Image.open(
            filepath
        ).convert("RGB")

        gown_embedding = fclip.encode_images(
            [gown_image],
            batch_size=1
        )[0]

        gown_embedding = normalize_embedding(
            gown_embedding
        )

        fashion_score = cosine_similarity(
            query_embedding,
            gown_embedding
        )

        gown_color = get_color_histogram(
            gown_image
        )

        color_score = color_similarity(
            query_color,
            gown_color
        )

        final_score = (
            fashion_score * 0.85
            +
            color_score * 0.15
        )

        results.append(
            {
                "filename": filename,
                "score": final_score,
                "fashion_score": fashion_score,
                "color_score": color_score
            }
        )

        del gown_image
        del gown_embedding
        del gown_color

        gc.collect()

    except Exception as e:

        print(
            f"ERROR processing "
            f"{filename}: {e}"
        )


# ============================================================
# SORT
# ============================================================

results.sort(
    key=lambda item: item["score"],
    reverse=True
)


# ============================================================
# TOP RESULTS
# ============================================================

results = results[:12]


# ============================================================
# SAVE RESULTS
# ============================================================

os.makedirs(
    os.path.dirname(OUTPUT_FILE),
    exist_ok=True
)

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        results,
        file,
        indent=2
    )


# ============================================================
# DONE
# ============================================================

print("=" * 70)
print("FASHIONCLIP FINISHED")
print("=" * 70)

print(
    f"Saved {len(results)} results to:"
)

print(
    OUTPUT_FILE
)

for result in results:

    print(
        result["filename"],
        f"{result['score']:.4f}"
    )