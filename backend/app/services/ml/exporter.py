"""
Model export pipeline.

Supports:
  - ONNX export (for lightweight Render inference)
  - Slim joblib export (strip training artifacts)
  - Model import from uploaded files
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def export_to_onnx(
    joblib_path: str,
    output_path: Optional[str] = None,
) -> str:
    """
    Convert a joblib tree model to ONNX format.

    Requires skl2onnx and onnxmltools (local-only deps).
    Returns the path to the exported ONNX file.
    """
    import joblib
    import numpy as np

    data = joblib.load(joblib_path)
    model = data["model"]
    feature_names = data["feature_names"]
    n_features = len(feature_names)

    if output_path is None:
        output_path = joblib_path.replace(".joblib", ".onnx")

    model_type_name = type(model).__name__.lower()

    try:
        # Try sklearn's native ONNX converter first
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType

        initial_type = [("input", FloatTensorType([None, n_features]))]
        onnx_model = convert_sklearn(model, initial_types=initial_type)

    except (ImportError, Exception) as e:
        logger.info("skl2onnx direct conversion failed (%s), trying onnxmltools", e)

        try:
            import onnxmltools
            from onnxmltools.convert.common.data_types import FloatTensorType

            initial_type = [("input", FloatTensorType([None, n_features]))]

            if "lightgbm" in model_type_name or "lgbm" in model_type_name:
                from onnxmltools.convert import convert_lightgbm
                onnx_model = convert_lightgbm(model, initial_types=initial_type)
            elif "xgb" in model_type_name:
                from onnxmltools.convert import convert_xgboost
                onnx_model = convert_xgboost(model, initial_types=initial_type)
            elif "catboost" in model_type_name:
                from onnxmltools.convert import convert_catboost
                onnx_model = convert_catboost(model, initial_types=initial_type)
            else:
                raise ValueError(f"Unsupported model type for ONNX: {model_type_name}")

        except ImportError:
            raise ImportError(
                "ONNX export requires skl2onnx and/or onnxmltools. "
                "Install locally: pip install skl2onnx onnxmltools"
            )

    # Save ONNX model
    with open(output_path, "wb") as f:
        f.write(onnx_model.SerializeToString())

    logger.info("Exported ONNX model: %s (%.1f KB)", output_path, os.path.getsize(output_path) / 1024)
    return output_path


def export_joblib_slim(
    joblib_path: str,
    output_path: Optional[str] = None,
) -> str:
    """
    Create a slim joblib file by stripping training artifacts.
    Keeps only: model, feature_names, target_name, model_type.
    """
    import joblib

    data = joblib.load(joblib_path)

    slim = {
        "model": data["model"],
        "feature_names": data["feature_names"],
        "target_name": data.get("target_name", "direction"),
        "model_type": data.get("model_type", "unknown"),
    }

    if output_path is None:
        output_path = joblib_path.replace(".joblib", "_slim.joblib")

    joblib.dump(slim, output_path, compress=3)

    original_size = os.path.getsize(joblib_path)
    slim_size = os.path.getsize(output_path)
    logger.info(
        "Exported slim joblib: %s (%.1f KB → %.1f KB, %.0f%% reduction)",
        output_path, original_size / 1024, slim_size / 1024,
        (1 - slim_size / original_size) * 100 if original_size > 0 else 0,
    )
    return output_path


def predict_onnx(
    onnx_path: str,
    X: list[list[float]],
) -> list:
    """
    Run inference using ONNX Runtime.
    Returns predictions as a flat list.
    """
    import numpy as np

    try:
        import onnxruntime as ort
    except ImportError:
        raise ImportError("onnxruntime not installed. Install: pip install onnxruntime")

    session = ort.InferenceSession(onnx_path)
    input_name = session.get_inputs()[0].name

    X_np = np.array(X, dtype=np.float32)
    result = session.run(None, {input_name: X_np})

    # result[0] = predictions, result[1] = probabilities (for classifiers)
    predictions = result[0].flatten().tolist()
    return predictions


def import_model(
    uploaded_path: str,
    model_id: int,
    model_dir: str,
) -> tuple[str, str]:
    """
    Import an uploaded model file (ONNX or joblib).

    Returns (saved_path, model_format).
    """
    import shutil

    ext = Path(uploaded_path).suffix.lower()
    if ext not in (".onnx", ".joblib"):
        raise ValueError(f"Unsupported model format: {ext}. Use .onnx or .joblib")

    dest = os.path.join(model_dir, f"model_{model_id}{ext}")
    shutil.copy2(uploaded_path, dest)

    logger.info("Imported model: %s → %s", uploaded_path, dest)
    return dest, ext.lstrip(".")
