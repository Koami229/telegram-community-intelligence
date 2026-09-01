"""
Tests: MonitoringWorker unit tests.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.monitoring import MonitoringWorker


@pytest.mark.asyncio
async def test_start_no_op_when_not_authenticated() -> None:
    """start() should be a no-op when Telegram is not connected."""
    worker = MonitoringWorker()
    # Patch the module-level import in monitoring.py
    with patch("app.workers.monitoring.telegram_service") as mock_tg:
        mock_tg.is_connected.return_value = False
        mock_tg.is_authorized = AsyncMock(return_value=False)
        await worker.start()
    assert not worker._running


@pytest.mark.asyncio
async def test_start_loads_groups_from_db() -> None:
    """start() should populate _monitored_group_ids from the DB."""
    worker = MonitoringWorker()

    mock_group = MagicMock()
    mock_group.telegram_group_id = -100111

    mock_client = MagicMock()
    mock_client.on = MagicMock(return_value=lambda f: f)  # decorator no-op

    mock_session = AsyncMock()

    with (
        patch("app.workers.monitoring.telegram_service") as mock_tg,
        patch("app.workers.monitoring.get_all_groups", return_value=[mock_group]),
        patch("app.workers.monitoring.AsyncSessionFactory") as mock_factory,
    ):
        mock_tg.is_connected.return_value = True
        mock_tg.is_authorized = AsyncMock(return_value=True)
        mock_tg.get_client.return_value = mock_client
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        await worker.start()

    assert -100111 in worker._monitored_group_ids
    assert worker._running


def test_add_group_adds_to_watchlist() -> None:
    worker = MonitoringWorker()
    worker.add_group(-100999)
    assert -100999 in worker._monitored_group_ids


@pytest.mark.asyncio
async def test_stop_sets_running_false() -> None:
    worker = MonitoringWorker()
    worker._running = True
    await worker.stop()
    assert not worker._running


@pytest.mark.asyncio
async def test_process_event_skips_unmonitored_group() -> None:
    """Events from groups not in our watchlist are silently ignored."""
    worker = MonitoringWorker()
    worker._monitored_group_ids = {-100111}

    mock_event = MagicMock()
    mock_event.chat_id = -100999  # not in watchlist
    mock_event.action_message = None

    # Should not raise and should not write to DB
    with patch("app.workers.monitoring.AsyncSessionFactory") as mock_factory:
        await worker._process_chat_action(mock_event)
        mock_factory.assert_not_called()
