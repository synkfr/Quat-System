# Lessons Learned

## CoinSwitch Pro API
- **Endpoint Timestamps**: Even if an endpoint like `/trade/api/v2/candles` accepts a `limit` parameter, it may still strictly require `start_time` and `end_time` parameters in milliseconds to function properly. Always calculate and define exact timestamp windows retroactively based on the limit if they are not passed explicitly.
- **Interval Formatting**: The CoinSwitch `/candles` endpoint demands the interval parameter be strictly parsed as a string containing solely the integer value representing minutes (i.e. `"15"`, `"60"`, `"240"`). Do not pass strings with letters like `"15m"` or `"1h"` as this will cause a generic `422` invalid format formatting error.

## Common Bugs & Fixes
- **Streamlit CSS Syntax Error**: When injecting CSS into an f-string (e.g., `st.markdown(f"<style>...")`), literal CSS braces `{}` must be escaped as `{{` and `}}`. Otherwise, Python attempts to interpolate the content inside `{}` as a variable or expression, leading to `NameError` or `SyntaxError`.
    - *Example Fix*: `.className {{ color: {COLORS['text']}; }}`

## API Response Keys
* **Never assume the key names in an API response.** When fetching from `/trade/api/v2/user/portfolio`, the available Indian Rupee wallet value is keyed under `main_balance`, not `balance`. Always run a live test probe (`test_portfolio.py`) to confirm payload schemas.

## UI & Dashboard
- **Sidebar Variable Scoping**: Streamlit processes pages top-to-bottom. If your sidebar assistant depends on a variable (like `symbol`) chosen in the main layout, define the sidebar block *after* the variable selection logic to avoid `NameError`.
- **Bot Heartbeat**: When displaying status from a shared file (like `.bot_status.json`), verify the `timestamp` hasn't gone stale. If the last update is > 2 minutes old, the bot has likely crashed or stopped; show "OFFLINE" to avoid misleading the user.
