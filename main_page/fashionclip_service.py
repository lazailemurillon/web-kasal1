import os
import tempfile
import gc

import numpy as np
from PIL import Image
from fashion_clip.fashion_clip import FashionCLIP


# ============================================================
# LOAD FASHIONCLIP ONLY ONCE
# ============================================================

_fclip = None


def get_fashionclip():
    global _fclip

    if _fclip is None:
        print("Loading FashionCLIP...")

        _fclip = FashionCLIP("fashion-clip")

        print("FashionCLIP loaded successfully.")

    return _fclip


# ============================================================
# CREATE FASHIONCLIP EMBEDDING
# ============================================================

def get_image_embedding(image_path):
    """
    Creates a normalized FashionCLIP embedding.
    """

    fclip = get_fashionclip()

    embeddings = fclip.encode_images(
        [image_path],
        batch_size=1
    )

    embedding = np.asarray(
        embeddings[0],
        dtype=np.float32
    )

    norm = np.linalg.norm(embedding)

    if norm != 0:
        embedding /= norm

    return embedding


# ============================================================
# COSINE SIMILARITY
# ============================================================

def cosine_similarity(vector_a, vector_b):
    """
    Cosine similarity between two vectors.
    """

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

def get_color_histogram(image_path):
    """
    Creates the same 18 x 5 x 5 HSV histogram
    as the original implementation.
    """

    with Image.open(image_path) as image:

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

    # ========================================================
    # HUE
    # ========================================================

    hue = np.zeros_like(maximum)

    mask = difference != 0

    # Red
    mask_r = mask & (maximum == r)

    hue[mask_r] = (
        60 *
        ((g[mask_r] - b[mask_r]) /
         difference[mask_r])
    ) % 360

    # Green
    mask_g = mask & (maximum == g)

    hue[mask_g] = (
        60 *
        ((b[mask_g] - r[mask_g]) /
         difference[mask_g])
        + 120
    ) % 360

    # Blue
    mask_b = mask & (maximum == b)

    hue[mask_b] = (
        60 *
        ((r[mask_b] - g[mask_b]) /
         difference[mask_b])
        + 240
    ) % 360

    # ========================================================
    # SATURATION
    # ========================================================

    saturation = np.zeros_like(maximum)

    nonzero_max = maximum != 0

    saturation[nonzero_max] = (
        difference[nonzero_max]
        /
        maximum[nonzero_max]
    )

    # ========================================================
    # HISTOGRAM
    # ========================================================

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

    # Put every pixel into its HSV bin
    for h, s, v in zip(
        hue_index.flat,
        saturation_index.flat,
        value_index.flat
    ):
        histogram[h, s, v] += 1

    # Normalize
    total = histogram.sum()

    if total > 0:
        histogram /= total

    return histogram.ravel()


# ============================================================
# COLOR SIMILARITY
# ============================================================

def color_similarity(color_a, color_b):
    """
    Histogram intersection.

    1.0 = very similar color distribution
    0.0 = very different color distribution
    """

    similarity = np.minimum(
        color_a,
        color_b
    ).sum()

    return float(
        np.clip(
            similarity,
            0.0,
            1.0
        )
    )


# ============================================================
# FINAL SIMILARITY
# ============================================================

def calculate_final_similarity(
    fashion_score,
    color_score
):
    """
    Same weighting as original:

    FashionCLIP = 85%
    Color = 15%
    """

    FASHION_WEIGHT = 0.85
    COLOR_WEIGHT = 0.15

    return (
        fashion_score * FASHION_WEIGHT
        +
        color_score * COLOR_WEIGHT
    )


# ============================================================
# FIND SIMILAR GOWNS
# ============================================================

def find_similar_gowns(
    uploaded_file,
    gowns,
    top_k=10
):
    """
    Finds gowns similar to the uploaded inspiration image.

    Matching:

    85% FashionCLIP
    15% color

    Different colors are still allowed.
    """

    # ========================================================
    # FILE EXTENSION
    # ========================================================

    filename = uploaded_file.name.lower()

    if filename.endswith(".png"):
        suffix = ".png"

    elif filename.endswith(".webp"):
        suffix = ".webp"

    else:
        suffix = ".jpg"

    # ========================================================
    # SAVE UPLOADED IMAGE TEMPORARILY
    # ========================================================

    temp_image_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False
        ) as temp_file:

            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)

            temp_image_path = temp_file.name

        # ====================================================
        # QUERY IMAGE
        # ====================================================

        query_embedding = get_image_embedding(
            temp_image_path
        )

        query_color = get_color_histogram(
            temp_image_path
        )

        print("\n" + "=" * 70)
        print("QUERY")
        print("=" * 70)

        print(
            "Embedding shape:",
            query_embedding.shape
        )

        results = []

        # ====================================================
        # COMPARE WITH GOWNS
        # ====================================================

        for gown in gowns:

            if not gown.image:
                continue

            gown_embedding = None
            gown_color = None

            try:

                gown_image_path = gown.image.path

                # ------------------------------------------------
                # FASHIONCLIP
                # ------------------------------------------------

                gown_embedding = get_image_embedding(
                    gown_image_path
                )

                fashion_score = cosine_similarity(
                    query_embedding,
                    gown_embedding
                )

                # ------------------------------------------------
                # COLOR
                # ------------------------------------------------

                gown_color = get_color_histogram(
                    gown_image_path
                )

                color_score = color_similarity(
                    query_color,
                    gown_color
                )

                # ------------------------------------------------
                # FINAL SCORE
                # ------------------------------------------------

                final_score = calculate_final_similarity(
                    fashion_score,
                    color_score
                )

                results.append({
                    "id": gown.id,
                    "score": final_score,
                    "fashion_score": fashion_score,
                    "color_score": color_score
                })

            except Exception as e:

                print(
                    f"Could not process gown "
                    f"{gown.id}: {e}"
                )

            finally:

                # Release temporary arrays
                gown_embedding = None
                gown_color = None

                gc.collect()

        # ====================================================
        # SORT RESULTS
        # ====================================================

        results.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        # ====================================================
        # MINIMUM SIMILARITY
        # ====================================================

        MIN_SIMILARITY = 0.60

        results = [
            result
            for result in results
            if result["score"] >= MIN_SIMILARITY
        ]

        # ====================================================
        # DEBUG OUTPUT
        # ====================================================

        print("\n" + "=" * 70)
        print("MATCHING GOWNS")
        print("=" * 70)

        for result in results:

            print("\n" + "-" * 70)

            print(
                f"GOWN ID: {result['id']}"
            )

            print(
                f"FINAL SCORE: "
                f"{result['score']:.6f}"
            )

            print(
                f"FASHION SCORE: "
                f"{result['fashion_score']:.6f}"
            )

            print(
                f"COLOR SCORE: "
                f"{result['color_score']:.6f}"
            )

            print(
                f"FINAL SCORE: "
                f"{result['score'] * 100:.2f}%"
            )

            print("-" * 70)

        # ====================================================
        # RETURN TOP K
        # ====================================================

        final_results = [
            {
                "id": result["id"],
                "score": result["score"],
                "fashion_score": result["fashion_score"],
                "color_score": result["color_score"]
            }
            for result in results[:top_k]
        ]

        return final_results

    finally:

        # ====================================================
        # DELETE TEMPORARY IMAGE
        # ========================================================

        if (
            temp_image_path
            and os.path.exists(temp_image_path)
        ):
            os.remove(temp_image_path)

        # Release unused Python memory
        gc.collect()