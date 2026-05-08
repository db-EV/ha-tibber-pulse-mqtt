# Changelog

## [0.3.3]
### Fixed
- Fixed External MQTT connection crashes with
  `OSError: Int or String expected` caused by invalid or improperly saved
  host/port values. (#9)
- Fixed crash when receiving MQTT messages due to callbacks being handled
  from the MQTT thread instead of the Home Assistant event loop.

### Improved
- MQTT host is now validated and normalized before connecting.
- MQTT port is now safely converted to an integer (handles values like `1883.0`).
- ExternalMQTTClient now correctly uses the Home Assistant event loop when
  dispatching incoming messages.

## [0.3.2]
### Changed
- Documentation updates only
  - Updated HACS installation instructions now that the integration is an official HACS repository
  - Added detailed, self-contained instructions for configuring Tibber Pulse and bridging MQTT traffic to Tibber Cloud

> Note: This release contains documentation changes only. No code changes.

## [0.3.1]
### Fixed
- HACS country removed.

## [0.3.0]
### Added
- New Tibber Pulse icons for Home Assistant Brands integration.
- Extended MQTT `+` wildcard support with regex-based filtering for embedded wildcard patterns.
- Added full Finnish (Suomi) translation.

### Changed
- UI precision settings migrated to OBIS metadata database.
- Translations refactored to use Home Assistant’s native translation system.
  - Removed custom language selection from config flow.
- Updated `requirements.txt` to align with HA 2026.3.0 Brand icon requirements.

### Improved
- mqtt_client: Improved error handling and added shared helper utilities.
- Deterministic sensor registry retrieval order for stable entity creation/update.
- Converted sensor creation/update pipeline to full async to align with HA best practices.
  - Introduced `asyncio.Lock` for thread-safe entity updates.
  - All external-thread calls now properly scheduled via `loop.call_soon_threadsafe`.
- **Async lifecycle & shutdown:**
  - `coordinator.py`: Robust HA stop handling using `async_listen` with self-unsubscribe on first fire; unload callback now a proper async function; idempotent `async_stop`.
  - `dispatcher.py`: Added `async_start/async_stop`, cancel-safe workers with periodic wake-ups, proper `CancelledError` handling, and `task.add_done_callback` to capture worker exceptions.
  - `dispatcher.py`: Introduced `_threadsafe_call_sm` (executor-loop) and `_loop_call_sm` (on-loop) to safely invoke `SensorManager` methods regardless of sync/async implementation.
  - `sensor.py`: Safer `async_write_ha_state` scheduling (immediate on loop; thread-safe scheduling off loop).

### Fixed
- Eliminated race conditions and non-deterministic behavior during sensor creation.
- Resolved warnings such as:
  - “coroutine was never awaited”
  - “hass.async_create_task called from a thread other than the event loop”
- **Resolved shutdown/reload errors:**
  - “Task was destroyed but it is pending!”
  - “Task exception was never retrieved”
  - “Unable to remove unknown job listener … ValueError: list.remove(x): x not in list”
  - “TypeError: a coroutine was expected, got <Task finished …>”

### Compatibility
- Compatible with all previous configurations.
- Home Assistant **2026.3.0+** recommended for complete Brand icon support.
