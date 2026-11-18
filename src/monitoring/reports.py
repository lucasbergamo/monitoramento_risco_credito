"""Relatório operacional HTML com estado ausente explícito e navegação local."""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from mlflow import MlflowClient

from src.monitoring.tracking import recent_runs
from src.utils.config import Settings
from src.utils.manifest import read_manifest, write_manifest


def build_report(settings: Settings, campaign_id: str | None = None) -> dict[str, Any]:
    root = settings.artifacts_dir / "runs"
    root.mkdir(parents=True, exist_ok=True)
    campaign = None
    campaign_directory = None
    if campaign_id is not None:
        from src.pipeline import verify_evidence

        verify_evidence(settings, campaign_id)
        campaign_directory = settings.artifacts_dir / "campaigns" / campaign_id
        campaign = read_manifest(campaign_directory / "manifest.json")
        detection = read_manifest(campaign_directory / "drift_summary.json")
        scenario_path = campaign_directory / "scenario_evaluation.json"
    else:
        detection = _latest_json(root, "summary.json", exclude=".")
        scenario_path = settings.data_dir / "scenarios/evaluation.json"
    scenario = read_manifest(scenario_path) if scenario_path.is_file() else None
    scenario_matches = bool(
        scenario
        and detection
        and scenario.get("scenario_version") == detection.get("scenario_version")
        and scenario.get("model_version") == detection.get("model_version")
    )
    try:
        if campaign is None:
            runs = recent_runs(settings)
        else:
            client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
            runs = []
            for run_id in campaign["run_ids"].values():
                run = client.get_run(run_id)
                runs.append(
                    {
                        "run_id": run.info.run_id,
                        "run_name": run.data.tags.get("mlflow.runName", "unnamed"),
                        "experiment": run.info.experiment_id,
                        "status": run.info.status,
                        "start_time": run.info.start_time,
                        "metrics": run.data.metrics,
                    }
                )
        tracking_status = "available"
    except Exception:
        runs = []
        tracking_status = "unavailable"
        if campaign is not None:
            raise

    data_layer = _data_layer(settings)
    model_layer = _model_layer(settings)
    pipeline_layer = _pipeline_layer(detection)
    resources_layer = _resources_layer(
        runs, detection.get("tracking_run_id") if detection else None
    )

    alerts = []
    if detection is not None:
        alerts.extend(
            {
                "scenario": comparison.get("comparison"),
                "window_index": comparison.get("window_index"),
                **event,
            }
            for comparison in detection.get("results", [])
            for event in comparison.get("alerts", [])
        )
    if scenario_matches and scenario is not None:
        gate = scenario.get("gate", {})
        last_pair = scenario.get("paired_effects", [])[-1:] or []
        increase = last_pair[0].get("brier_difference") if last_pair else None
        threshold = gate.get("minimum_brier_increase_exclusive")
        if increase is not None and threshold is not None and increase > threshold:
            alerts.append(
                {
                    "type": "performance_degraded",
                    "scenario": "concept_drift",
                    "window_index": last_pair[0].get("window_index"),
                    "severity": "critical",
                    "condition": f"Brier pareado {increase:.6f} > {threshold:.6f}",
                    "action": "Investigar mudança de conceito e revisar desempenho supervisionado",
                }
            )
        rejected = [
            item
            for item in scenario.get("results", [])
            if item.get("status") == "contract_rejected"
        ]
        for item in rejected:
            alerts.append(
                {
                    "type": "rejection",
                    "scenario": item.get("scenario"),
                    "window_index": item.get("window_index"),
                    "severity": "warning",
                    "condition": f"Contrato rejeitou cenário na janela {item.get('window_index')}",
                    "action": "Inspecionar regra agregada e corrigir a origem do lote",
                }
            )

    report = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "campaign_status": campaign.get("status") if campaign else None,
        "campaign_run_ids": campaign.get("run_ids") if campaign else None,
        "tracking_status": tracking_status,
        "tracking_uri": settings.mlflow_tracking_uri,
        "tracking_ui_uri": settings.mlflow_ui_uri,
        "run_count": len(runs),
        "runs": runs,
        "layers": {
            "data": data_layer,
            "model": model_layer,
            "pipeline": pipeline_layer,
            "resources": resources_layer,
        },
        "drift_run_id": detection.get("run_id") if detection else None,
        "scenario_version": scenario.get("scenario_version") if scenario else None,
        "scenario_evaluation_status": "available" if scenario_matches else "unavailable",
        "scenario_comparison": (
            _scenario_comparison(scenario) if scenario_matches and scenario is not None else []
        ),
        "alerts": alerts,
        "sources": {
            "drift_summary": (
                "drift_summary.json"
                if campaign_id and detection
                else _relative_link(root, detection.get("run_id"), "summary.json")
                if detection
                else None
            ),
            "scenario_evaluation": (
                "scenario_evaluation.json"
                if campaign_id and scenario_matches
                else "../../data/scenarios/evaluation.json"
                if scenario_matches
                else None
            ),
        },
    }
    output = campaign_directory or root
    write_manifest(output / "summary.json", _json_safe(report))
    _write_html(output / "index.html", report)
    return report


def _latest_json(root: Path, filename: str, *, exclude: str) -> dict | None:
    candidates = [path for path in root.glob(f"*/{filename}") if path.parent.name != exclude]
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    return json.loads(latest.read_text(encoding="utf-8"))


def _data_layer(settings: Settings) -> dict[str, Any]:
    manifest = settings.data_dir / "gold/dataset_manifest.json"
    if not manifest.is_file():
        return {"status": "unavailable"}
    value = read_manifest(manifest)
    row_count = value.get("row_count")
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count <= 0:
        return {"status": "unavailable"}
    return {"status": "available", "row_count": row_count}


def _model_layer(settings: Settings) -> dict[str, Any]:
    manifest = settings.models_dir / "current/manifest.json"
    if not manifest.is_file():
        return {"status": "unavailable"}
    value = read_manifest(manifest)
    validation = value.get("validation", {}).get("model", {})
    auc, brier, model_version = (
        validation.get("roc_auc"),
        validation.get("brier"),
        value.get("version"),
    )
    if (
        not isinstance(model_version, str)
        or not isinstance(auc, (float, int))
        or not isinstance(brier, (float, int))
        or not math.isfinite(auc)
        or not math.isfinite(brier)
    ):
        return {"status": "unavailable"}
    return {
        "status": "available",
        "model_version": model_version,
        "validation_roc_auc": auc,
        "validation_brier": brier,
    }


def _pipeline_layer(detection: dict | None) -> dict[str, Any]:
    if (
        detection is None
        or not detection.get("run_id")
        or not detection.get("model_version")
        or not detection.get("results")
    ):
        return {"status": "unavailable"}
    return {
        "status": "available",
        "run_id": detection.get("run_id"),
        "model_version": detection.get("model_version"),
        "comparison_count": len(detection.get("results", [])),
    }


def _resources_layer(runs: list[dict], tracking_run_id: str | None) -> dict[str, Any]:
    if not tracking_run_id:
        return {"status": "unavailable"}
    run = next((item for item in runs if item["run_id"] == tracking_run_id), None)
    if run is None:
        return {"status": "unavailable", "run_id": tracking_run_id}
    metrics = run.get("metrics", {})
    names = (
        "resources.duration_seconds",
        "resources.cpu_seconds",
        "resources.rss_peak_bytes",
    )
    if any(name not in metrics for name in names):
        return {"status": "unavailable", "run_id": tracking_run_id}
    values = [metrics[name] for name in names]
    if any(
        not isinstance(value, (float, int))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        return {"status": "unavailable", "run_id": tracking_run_id}
    return {
        "status": "available",
        "run_id": tracking_run_id,
        "duration_seconds": metrics[names[0]],
        "cpu_seconds": metrics[names[1]],
        "rss_peak_bytes": metrics[names[2]],
        "scope": "process_and_children_excluded",
    }


def _scenario_comparison(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in scenario.get("results", []):
        name = item.get("scenario")
        if not isinstance(name, str):
            continue
        if name not in latest or item.get("window_index", -1) > latest[name].get(
            "window_index", -1
        ):
            latest[name] = item
    return [
        {
            "scenario": name,
            "window_index": item.get("window_index"),
            "status": item.get("status", "unavailable"),
            "roc_auc": (item.get("metrics") or {}).get("roc_auc"),
            "brier": (item.get("metrics") or {}).get("brier"),
        }
        for name, item in sorted(latest.items())
    ]


def _relative_link(root: Path, run_id: str | None, filename: str) -> str:
    if not run_id:
        return ""
    return f"{run_id}/{filename}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write_html(path: Path, report: dict[str, Any]) -> None:
    status = report["tracking_status"]
    color = {"available": "#13795b", "unavailable": "#9a6700"}[status]
    rows = []
    for item in report["runs"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['experiment'])}</td>"
            f"<td>{html.escape(item['run_name'])}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td><code>{html.escape(item['run_id'])}</code></td></tr>"
        )
    if not rows:
        rows.append(
            '<tr><td colspan="4" class="empty">Indisponível: nenhuma run recuperada.</td></tr>'
        )
    alerts = []
    for item in report["alerts"]:
        severity = "critical" if item.get("severity") == "critical" else "warning"
        alerts.append(
            f'<li class="{severity}"><strong>{html.escape(item["type"])}</strong>: '
            f"Cenário {html.escape(str(item.get('scenario', 'indisponível')))}, "
            f"janela {html.escape(str(item.get('window_index', 'indisponível')))}. "
            f"{html.escape(item.get('condition', 'condição não informada'))}. "
            f"{html.escape(item.get('action', 'Ação não informada.'))}</li>"
        )
    if not alerts:
        alerts.append('<li class="empty">Indisponível: ainda não há alertas observados.</li>')
    alert_chart = _alert_chart(report["alerts"])
    links = []
    for label, target in (
        ("Resumo de drift", report["sources"]["drift_summary"]),
        ("Avaliação de cenários", report["sources"]["scenario_evaluation"]),
    ):
        if target:
            links.append(f'<li><a href="{html.escape(target, quote=True)}">{label}</a></li>')
    if not links:
        links.append('<li class="empty">Indisponível: relatórios locais ainda não gerados.</li>')
    scenario_rows = []
    for item in report["scenario_comparison"]:
        metrics = item["status"] == "available"
        auc = (
            f"{item['roc_auc']:.4f}" if metrics and item["roc_auc"] is not None else "Indisponível"
        )
        brier = f"{item['brier']:.4f}" if metrics and item["brier"] is not None else "Indisponível"
        scenario_rows.append(
            "<tr>"
            f"<td>{html.escape(item['scenario'])}</td>"
            f"<td>{item['window_index']}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td>{auc}</td><td>{brier}</td></tr>"
        )
    if not scenario_rows:
        scenario_rows.append(
            '<tr><td colspan="5" class="empty">Indisponível: avaliação ausente '
            "ou desatualizada.</td></tr>"
        )
    layer_names = {
        "data": "Dados",
        "model": "Modelo",
        "pipeline": "Pipeline",
        "resources": "Recursos do processo",
    }
    layer_cards = []
    for name, label in layer_names.items():
        details = report["layers"][name]
        if details["status"] != "available":
            value = "Indisponível"
            state_class = "empty"
        elif name == "data":
            value = f"{details['row_count']:,} registros"
            state_class = "available"
        elif name == "model":
            value = (
                f"Validação: AUC {details['validation_roc_auc']:.4f}, "
                f"Brier {details['validation_brier']:.4f}"
            )
            state_class = "available"
        elif name == "pipeline":
            value = f"{details['comparison_count']} comparações; run {details['run_id']}"
            state_class = "available"
        else:
            value = (
                f"Tempo de CPU do processo: {details['cpu_seconds']:.3f} s; "
                f"pico RSS amostrado: {details['rss_peak_bytes'] / 1024**2:.2f} MiB; "
                f"tempo de parede da operação: {details['duration_seconds']:.3f} s"
            )
            state_class = "available"
        layer_cards.append(
            f'<article><h3>{label}</h3><p class="{state_class}">{html.escape(value)}</p></article>'
        )
    document = f"""<!doctype html>
<html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Observabilidade de risco de crédito</title>
<style>
body{{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;
padding:0 1rem;color:#172b4d}}
h1,h2{{color:#102a43}} .status{{color:{color};font-weight:700}}
table{{border-collapse:collapse;width:100%}}
th,td{{border-bottom:1px solid #d9e2ec;padding:.65rem;text-align:left}}
th{{background:#f0f4f8}}
.warning{{color:#8a4b08}} .critical{{color:#b42318}}
li{{margin:.5rem 0}} .empty{{color:#667085}}
.available{{color:#13795b}}
.layers{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem}}
article{{border:1px solid #d9e2ec;border-radius:.5rem;padding:1rem}}
</style><body><h1>Observabilidade operacional</h1>
<p>Campanha: <code>{html.escape(str(report.get("campaign_id") or "indisponível"))}</code></p>
<p>Tracking: <span class="status">{html.escape(status)}</span>.
<a href="{html.escape(report["tracking_ui_uri"], quote=True)}">UI MLflow no host</a></p>
<h2>Camadas operacionais</h2><section class="layers">{"".join(layer_cards)}</section>
<h2>Execuções ({report["run_count"]})</h2><table><thead><tr>
<th>Experimento</th><th>Run</th><th>Estado</th><th>Identificador</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table>
<h2>Alertas ({len(report["alerts"])})</h2><ul>{"".join(alerts)}</ul>
<h3>Quantidade por tipo de alerta</h3>{alert_chart}
<h2>Comparação de cenários</h2><table><thead><tr>
<th>Cenário</th><th>Janela</th><th>Estado</th><th>ROC AUC</th><th>Brier</th>
</tr></thead><tbody>{"".join(scenario_rows)}</tbody></table>
<h2>Relatórios locais</h2><ul>{"".join(links)}</ul></body></html>"""
    path.write_text(document, encoding="utf-8")


def _alert_chart(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return '<p class="empty">Indisponível: sem observações para comparar.</p>'
    counts: dict[str, tuple[int, str]] = {}
    for alert in alerts:
        name = str(alert.get("type", "unknown"))
        count, color = counts.get(name, (0, "#667085"))
        if alert.get("severity") == "critical":
            color = "#b42318"
        elif alert.get("severity") == "warning" and color != "#b42318":
            color = "#8a4b08"
        counts[name] = (count + 1, color)
    maximum = max(count for count, _ in counts.values())
    bars = []
    for index, (name, (count, color)) in enumerate(sorted(counts.items())):
        y = 24 + index * 34
        width = max(3, int(280 * count / maximum))
        bars.append(
            f'<text x="0" y="{y + 14}">{html.escape(name)}</text>'
            f'<rect x="145" y="{y}" width="{width}" height="20" fill="{color}"/>'
            f'<text x="{155 + width}" y="{y + 15}">{count}</text>'
        )
    height = 30 + 34 * len(bars)
    return (
        f'<svg role="img" aria-label="Quantidade de alertas por tipo" '
        f'viewBox="0 0 480 {height}" width="480" height="{height}">'
        f"{''.join(bars)}</svg>"
    )
