from flask import Blueprint, current_app, jsonify, render_template, request

from .services.executor import ActionExecutor
from .services.presets import PresetService
from .services.registry import RegistryService

api_bp = Blueprint("drayops", __name__)


def _services():
    base_dir = current_app.config["DRAYOPS_BASE_DIR"]
    return (
        PresetService(base_dir / "presets"),
        RegistryService(base_dir / "data"),
        ActionExecutor(),
    )


def _target_payload(target: dict) -> dict:
    return {
        **target,
        "config_fields": target.get("config_fields", []),
        "action_fields": target.get("action_fields", {}),
    }


@api_bp.route("/")
def index():
    return render_template("index.html")


@api_bp.route("/api/presets")
def list_presets():
    presets, _, _ = _services()
    return jsonify({"presets": presets.list_presets()})


@api_bp.route("/api/targets")
def list_targets():
    _, registry, _ = _services()
    return jsonify({"targets": [_target_payload(target) for target in registry.list_targets()]})


@api_bp.route("/api/targets/<target_id>")
def get_target(target_id: str):
    _, registry, _ = _services()
    target = registry.get_target(target_id)
    if not target:
        return jsonify({"error": f"Unknown target: {target_id}"}), 404
    return jsonify({"target": _target_payload(target)})


@api_bp.route("/api/targets", methods=["POST"])
def create_target():
    presets, registry, _ = _services()
    payload = request.get_json() or {}
    preset_id = payload.get("preset_id")
    if not preset_id:
        return jsonify({"error": "preset_id is required"}), 400
    preset = presets.get_preset(preset_id)
    if not preset:
        return jsonify({"error": f"Unknown preset: {preset_id}"}), 404
    target = registry.create_target(preset, payload.get("overrides") or {})
    return jsonify({"ok": True, "target": _target_payload(target)}), 201


@api_bp.route("/api/targets/<target_id>", methods=["PATCH"])
def update_target(target_id: str):
    _, registry, _ = _services()
    payload = request.get_json() or {}
    target = registry.update_target(target_id, payload)
    if not target:
        return jsonify({"error": f"Unknown target: {target_id}"}), 404
    return jsonify({"ok": True, "target": _target_payload(target)})


@api_bp.route("/api/targets/<target_id>", methods=["DELETE"])
def delete_target(target_id: str):
    _, registry, _ = _services()
    deleted = registry.delete_target(target_id)
    if not deleted:
        return jsonify({"error": f"Unknown target: {target_id}"}), 404
    return jsonify({"ok": True})


@api_bp.route("/api/jobs")
def list_jobs():
    _, registry, _ = _services()
    return jsonify({"jobs": registry.list_jobs()})


@api_bp.route("/api/targets/<target_id>/actions/<action>", methods=["POST"])
def run_target_action(target_id: str, action: str):
    _, registry, executor = _services()
    payload = request.get_json() or {}
    target = registry.get_target(target_id)
    if not target:
        return jsonify({"error": f"Unknown target: {target_id}"}), 404
    try:
        result = executor.execute(target, action, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if result.get("config_updates"):
        target = registry.update_target(target_id, {"config": result["config_updates"]}) or target
    job = registry.record_job(target_id, action, result)
    return jsonify({"ok": True, "job": job, "result": result, "target": _target_payload(target)})


@api_bp.route("/api/vast/offers")
def vast_offers():
    _, _, executor = _services()
    try:
        offers = executor.search_vast_offers(
            max_dph=request.args.get("max_dph"),
            min_gpu_ram=request.args.get("min_gpu_ram"),
            gpu_name=request.args.get("gpu_name"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"offers": offers})


@api_bp.route("/api/vast/deploy", methods=["POST"])
def vast_deploy():
    presets, registry, executor = _services()
    payload = request.get_json() or {}
    preset_id = payload.get("preset_id")
    offer_id = payload.get("offer_id")
    if not preset_id or not offer_id:
        return jsonify({"error": "preset_id and offer_id are required"}), 400
    try:
        result = executor.deploy_vast_instance(preset_id, int(offer_id), payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    target = None
    preset = presets.get_preset(preset_id)
    if preset:
        overrides = {**(payload.get("overrides") or {}), **(result.get("config_updates") or {})}
        if "name" not in overrides or not overrides["name"]:
            overrides["name"] = f"{preset['name']} #{result.get('instance_id') or offer_id}"
        target = registry.create_target(preset, overrides)
    job = registry.record_job(None, f"vast-deploy:{preset_id}", result)
    return jsonify({"ok": True, "job": job, "result": result, "target": _target_payload(target) if target else None})
