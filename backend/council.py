"""3-stage LLM Council orchestration."""

from typing import List, Dict, Any, Tuple, Optional
from .openrouter import query_models_parallel, query_model
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL
from .usage import build_usage_request, summarize_usage_requests


class CouncilQuorumError(Exception):
    """Raised when too few council models respond to continue meaningfully."""

    def __init__(
        self,
        stage: str,
        successful: int,
        required: int,
        attempted_models: List[str],
    ):
        self.stage = stage
        self.successful = successful
        self.required = required
        self.attempted_models = attempted_models
        super().__init__(
            f"{stage} quorum failed: {successful} of {len(attempted_models)} "
            f"models responded; {required} required."
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "successful": self.successful,
            "required": self.required,
            "attempted_models": self.attempted_models,
            "message": str(self),
        }


def required_quorum(models: List[str]) -> int:
    """Require at least two responders for council behavior, unless only one model is configured."""
    return min(2, len(models))


async def stage1_collect_responses(
    user_query: str,
    council_models: List[str] | None = None
) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    messages = [{"role": "user", "content": user_query}]

    models = council_models or COUNCIL_MODELS

    # Query all models in parallel
    responses = await query_models_parallel(models, messages)

    # Format results
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', ''),
                "usage": build_usage_request(
                    kind="stage1",
                    usage=response.get("usage"),
                    model=model,
                ),
            })

    quorum = required_quorum(models)
    if len(stage1_results) < quorum:
        raise CouncilQuorumError("Stage 1", len(stage1_results), quorum, models)

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    council_models: List[str] | None = None
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]
    models = council_models or COUNCIL_MODELS

    if len(stage1_results) < 2 and len(models) > 1:
        raise CouncilQuorumError("Stage 2", len(stage1_results), 2, models)

    # Get rankings from all council models in parallel
    responses = await query_models_parallel(models, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed,
                "usage": build_usage_request(
                    kind="stage2",
                    usage=response.get("usage"),
                    model=model,
                ),
            })

    quorum = required_quorum(models)
    if len(stage2_results) < quorum:
        raise CouncilQuorumError("Stage 2", len(stage2_results), quorum, models)

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    chairman_model: str | None = None
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]
    model = chairman_model or CHAIRMAN_MODEL

    # Query the chairman model
    response = await query_model(model, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": model,
            "response": "Error: Unable to generate final synthesis.",
            "usage": None,
        }

    return {
        "model": model,
        "response": response.get('content', ''),
        "usage": build_usage_request(
            kind="stage3",
            usage=response.get("usage"),
            model=model,
        ),
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


def build_council_usage_metadata(
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    extra_requests: Optional[List[Optional[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Build request-level and aggregate usage metadata for one council turn."""
    requests: List[Optional[Dict[str, Any]]] = []
    requests.extend(result.get("usage") for result in stage1_results)
    requests.extend(result.get("usage") for result in stage2_results)
    requests.append(stage3_result.get("usage"))
    requests.extend(extra_requests or [])

    normalized_requests = [request for request in requests if isinstance(request, dict)]
    return {
        "requests": normalized_requests,
        "summary": summarize_usage_requests(normalized_requests),
    }


async def generate_conversation_title(user_query: str) -> Dict[str, Any]:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    model = "google/gemini-2.5-flash"

    # Use gemini-2.5-flash for title generation (fast and cheap)
    response = await query_model(model, messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return {
            "title": "New Conversation",
            "model": model,
            "usage": None,
        }

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return {
        "title": title or "New Conversation",
        "model": model,
        "usage": build_usage_request(
            kind="title_generation",
            usage=response.get("usage"),
            model=model,
        ),
    }


async def run_full_council(
    user_query: str,
    council_models: List[str] | None = None,
    chairman_model: str | None = None,
    bundle: Dict[str, Any] | None = None,
    extra_usage_requests: Optional[List[Optional[Dict[str, Any]]]] = None,
) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process.

    Args:
        user_query: The user's question

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses
    models = council_models or COUNCIL_MODELS
    chairman = chairman_model or CHAIRMAN_MODEL

    stage1_results = await stage1_collect_responses(user_query, models)

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(
        user_query,
        stage1_results,
        models
    )

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        chairman
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "usage": build_council_usage_metadata(
            stage1_results,
            stage2_results,
            stage3_result,
            extra_requests=extra_usage_requests,
        ),
    }

    if bundle:
        metadata["bundle"] = {
            "id": bundle["id"],
            "name": bundle["name"],
            "chairman_model": bundle["chairman_model"],
            "council_models": bundle["council_models"],
        }

    return stage1_results, stage2_results, stage3_result, metadata
