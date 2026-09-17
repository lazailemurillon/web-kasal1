import os
import tempfile

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
    Creates a FashionCLIP embedding.

    FashionCLIP captures overall fashion similarity including
    garment type, silhouette, style, texture, pattern, color,
    and other visual characteristics.
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

    # Normalize vector
    norm = np.linalg.norm(embedding)

    if norm != 0:
        embedding = embedding / norm

    return embedding


# ============================================================
# COSINE SIMILARITY
# ============================================================

def cosine_similarity(vector_a, vector_b):
    """
    Cosine similarity between two vectors.
    """

    vector_a = np.asarray(
        vector_a,
        dtype=np.float32
    )

    vector_b = np.asarray(
        vector_b,
        dtype=np.float32
    )

    norm_a = np.linalg.norm(vector_a)
    norm_b = np.linalg.norm(vector_b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(
        np.dot(vector_a, vector_b)
        / (norm_a * norm_b)
    )


# ============================================================
# SIMPLE COLOR HISTOGRAM
# ============================================================

def get_color_histogram(image_path):
    """
    Extracts the overall color distribution of an image.

    This is NOT used to require the same color.

    It is only a secondary signal that helps ranking.
    """

    image = Image.open(
        image_path
    ).convert("RGB")

    # Small image is enough for color distribution
    image = image.resize((64, 64))

    image_array = np.asarray(
        image,
        dtype=np.float32
    )

    # Convert RGB to HSV manually
    rgb = image_array / 255.0

    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]

    maximum = np.max(
        rgb,
        axis=2
    )

    minimum = np.min(
        rgb,
        axis=2
    )

    difference = maximum - minimum

    # --------------------------------------------------------
    # Hue
    # --------------------------------------------------------

    hue = np.zeros_like(maximum)

    mask = difference != 0

    # Red
    mask_r = (
        mask &
        (maximum == r)
    )

    hue[mask_r] = (
        60 *
        ((g[mask_r] - b[mask_r]) /
         difference[mask_r])
    ) % 360

    # Green
    mask_g = (
        mask &
        (maximum == g)
    )

    hue[mask_g] = (
        60 *
        ((b[mask_g] - r[mask_g]) /
         difference[mask_g])
        + 120
    ) % 360

    # Blue
    mask_b = (
        mask &
        (maximum == b)
    )

    hue[mask_b] = (
        60 *
        ((r[mask_b] - g[mask_b]) /
         difference[mask_b])
        + 240
    ) % 360

    # --------------------------------------------------------
    # Saturation
    # --------------------------------------------------------

    saturation = np.zeros_like(maximum)

    nonzero_max = maximum != 0

    saturation[nonzero_max] = (
        difference[nonzero_max]
        /
        maximum[nonzero_max]
    )

    # --------------------------------------------------------
    # Create histogram
    # --------------------------------------------------------

    hue_bins = 18
    saturation_bins = 5
    value_bins = 5

    hue_index = np.minimum(
        (hue / 360 * hue_bins).astype(int),
        hue_bins - 1
    )

    saturation_index = np.minimum(
        (saturation * saturation_bins).astype(int),
        saturation_bins - 1
    )

    value_index = np.minimum(
        (maximum * value_bins).astype(int),
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
        hue_index.flatten(),
        saturation_index.flatten(),
        value_index.flatten()
    ):
        histogram[h, s, v] += 1

    # Normalize
    total = histogram.sum()

    if total > 0:
        histogram /= total

    return histogram.flatten()


# ============================================================
# COLOR SIMILARITY
# ============================================================

def color_similarity(color_a, color_b):
    """
    Calculates color similarity.

    1.0 = very similar color distribution
    0.0 = very different color distribution

    IMPORTANT:
    This is only a secondary score.
    """

    color_a = np.asarray(
        color_a,
        dtype=np.float32
    )

    color_b = np.asarray(
        color_b,
        dtype=np.float32
    )

    # Histogram intersection
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
    Fashion/style is the dominant factor.

    FashionCLIP: 85%
    Color:       15%

    Color influences ranking but cannot dominate style.
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

    Matching priority:

        85% FashionCLIP
        15% color

    Therefore:

        silhouette/style = primary
        color            = secondary

    Different colors are still allowed.
    """

    # --------------------------------------------------------
    # Save uploaded image temporarily
    # --------------------------------------------------------

    suffix = ".jpg"

    if uploaded_file.name.lower().endswith(".png"):
        suffix = ".png"

    elif uploaded_file.name.lower().endswith(".webp"):
        suffix = ".webp"

    with tempfile.NamedTemporaryFile(
        suffix=suffix,
        delete=False
    ) as temp_file:

        for chunk in uploaded_file.chunks():
            temp_file.write(chunk)

        temp_image_path = temp_file.name

    try:

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

            try:

                gown_image_path = gown.image.path

                # --------------------------------------------
                # FashionCLIP
                # --------------------------------------------

                gown_embedding = get_image_embedding(
                    gown_image_path
                )

                fashion_score = cosine_similarity(
                    query_embedding,
                    gown_embedding
                )

                # --------------------------------------------
                # Color
                # --------------------------------------------

                gown_color = get_color_histogram(
                    gown_image_path
                )

                color_score = color_similarity(
                    query_color,
                    gown_color
                )

                # --------------------------------------------
                # Combined score
                # --------------------------------------------

                final_score = calculate_final_similarity(
                    fashion_score,
                    color_score
                )

                results.append({

                    "id": gown.id,

                    # Final ranking score
                    "score": final_score,

                    # Keep individual scores
                    "fashion_score": fashion_score,
                    "color_score": color_score,

                    # Debugging only
                    "embedding": gown_embedding
                })

            except Exception as e:

                print(
                    f"Could not process gown "
                    f"{gown.id}: {e}"
                )

        # ====================================================
        # SORT
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

                # Optional:
                # useful if you want to see why
                # the gown ranked where it did.
                "fashion_score":
                    result["fashion_score"],

                "color_score":
                    result["color_score"]
            }

            for result in results[:top_k]
        ]

        return final_results

    finally:

        # ----------------------------------------------------
        # Delete temporary uploaded image
        # ----------------------------------------------------

        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)