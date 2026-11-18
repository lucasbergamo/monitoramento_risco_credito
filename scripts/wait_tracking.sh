#!/bin/sh
# Compose controla a espera; a inspeção impede sucesso com saúde ainda starting.
set -eu
mode=start
if [ "${1:-}" = --status ]; then mode=status; shift; fi
timeout=${TRACKING_WAIT_TIMEOUT:-180}
case "$timeout" in ''|*[!0-9]*|0) echo "Prazo de prontidão inválido." >&2; exit 2 ;; esac
if ! [ "$timeout" -gt 0 ] 2>/dev/null; then
    echo "Prazo de prontidão inválido." >&2
    exit 2
fi
if [ "$#" -eq 0 ]; then set -- docker compose; fi
if [ "$mode" = status ]; then
    container=$("$@" ps --all --quiet mlflow)
    if [ -z "$container" ]; then
        echo "MLflow ausente neste projeto." >&2
        exit 1
    fi
    state=$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container")
    if [ "$state" = "running healthy" ]; then
        echo "OK"
        exit 0
    fi
    echo "MLflow ainda não está pronto: ${state}." >&2
    exit 1
fi
echo "Aguardando MLflow saudável (prazo: ${timeout}s)..." >&2
if "$@" up -d --wait --wait-timeout "$timeout" mlflow; then
    container=$("$@" ps --all --quiet mlflow)
    if [ -n "$container" ]; then
        state=$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container")
        if [ "$state" = "running healthy" ]; then
            echo "MLflow pronto." >&2
            exit 0
        fi
        echo "MLflow indisponível: estado ${state}." >&2
    else
        echo "MLflow indisponível: container ausente." >&2
    fi
fi
echo "Falha de prontidão do MLflow. Confira o estado com docker compose ps e os logs locais do serviço." >&2
exit 1
