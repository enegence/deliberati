"""OpenRouter API client for making LLM requests."""

import asyncio
import httpx
import time
from typing import List, Dict, Any, Optional
from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL
from .usage import normalize_openrouter_usage


RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    max_attempts: int = 2
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds
        max_attempts: Total attempts before returning None

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    attempts = max(1, max_attempts)

    for attempt in range(1, attempts + 1):
        started_at = time.monotonic()
        retry_prefix = f"attempt {attempt}/{attempts}"

        try:
            http_timeout = httpx.Timeout(
                timeout,
                connect=min(15.0, timeout),
                read=timeout,
                write=30.0,
                pool=15.0,
            )
            async with httpx.AsyncClient(timeout=http_timeout) as client:
                response = await client.post(
                    OPENROUTER_API_URL,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()

                data = response.json()

                if data.get("error"):
                    print(f"Error querying model {model} ({retry_prefix}): {data['error']}")
                    if attempt < attempts:
                        await asyncio.sleep(2 ** (attempt - 1))
                        continue
                    return None

                choices = data.get("choices")
                if not choices:
                    print(
                        f"Error querying model {model} ({retry_prefix}): "
                        f"missing choices in response {str(data)[:1000]}"
                    )
                    if attempt < attempts:
                        await asyncio.sleep(2 ** (attempt - 1))
                        continue
                    return None

                message = choices[0].get('message') or {}

                return {
                    'content': message.get('content'),
                    'reasoning_details': message.get('reasoning_details'),
                    'usage': normalize_openrouter_usage(
                        model,
                        data,
                        dict(response.headers),
                    ),
                }

        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            print(
                f"Error querying model {model} ({retry_prefix}): "
                f"HTTP {status_code} {e.response.text[:500]}"
            )
            if status_code in RETRYABLE_STATUS_CODES and attempt < attempts:
                await asyncio.sleep(2 ** (attempt - 1))
                continue
            return None
        except (httpx.TimeoutException, httpx.TransportError) as e:
            print(
                f"Error querying model {model} ({retry_prefix}): "
                f"{type(e).__name__} after {time.monotonic() - started_at:.1f}s: {e}"
            )
            if attempt < attempts:
                await asyncio.sleep(2 ** (attempt - 1))
                continue
            return None
        except Exception as e:
            print(f"Error querying model {model} ({retry_prefix}): {e}")
            if attempt < attempts:
                await asyncio.sleep(2 ** (attempt - 1))
                continue
            return None

    return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    max_attempts: int = 2
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    async def query_with_hard_timeout(model: str) -> Optional[Dict[str, Any]]:
        try:
            return await asyncio.wait_for(
                query_model(model, messages, timeout=timeout, max_attempts=max_attempts),
                timeout=(timeout + 10.0) * max(1, max_attempts),
            )
        except asyncio.TimeoutError:
            print(f"Hard timeout querying model {model} after {(timeout + 10.0) * max(1, max_attempts):.1f}s")
            return None

    # Create tasks for all models
    tasks = [query_with_hard_timeout(model) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}
