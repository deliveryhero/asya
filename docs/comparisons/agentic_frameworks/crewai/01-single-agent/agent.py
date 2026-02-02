"""
Minimal CrewAI Single Agent Example

This example demonstrates:
- Creating a single agent with role and goal
- Defining custom tools using the @tool decorator
- Creating and executing a task
- Running the agent through a Crew

The agent analyzes product reviews and extracts insights.
"""

from crewai import Agent, Task, Crew
from crewai.tools import tool


# Define custom tools using the @tool decorator
@tool("Sentiment Analyzer")
def analyze_sentiment(text: str) -> str:
    """
    Analyzes the sentiment of a given text.
    Returns positive, negative, or neutral.
    """
    # Simple mock sentiment analysis
    text_lower = text.lower()
    positive_words = ["good", "great", "excellent", "amazing", "love", "best"]
    negative_words = ["bad", "terrible", "awful", "hate", "worst", "poor"]

    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)

    if positive_count > negative_count:
        return "positive"
    elif negative_count > positive_count:
        return "negative"
    else:
        return "neutral"


@tool("Keyword Extractor")
def extract_keywords(text: str) -> str:
    """
    Extracts important keywords from the given text.
    Returns comma-separated keywords.
    """
    # Simple mock keyword extraction
    keywords = ["quality", "service", "price", "delivery", "product", "customer"]
    found_keywords = [kw for kw in keywords if kw in text.lower()]
    return ", ".join(found_keywords) if found_keywords else "No keywords found"


@tool("Review Summarizer")
def summarize_review(text: str) -> str:
    """
    Provides a brief summary of the review.
    Returns a one-line summary.
    """
    # Simple mock summarization
    words = text.split()
    if len(words) > 20:
        summary = " ".join(words[:20]) + "..."
    else:
        summary = text
    return f"Summary: {summary}"


def main():
    """Main function to run the single-agent example."""

    # Create a single agent
    reviewer_agent = Agent(
        role="Product Review Analyst",
        goal="Analyze product reviews and extract actionable insights about customer satisfaction",
        backstory=(
            "You are an expert at analyzing customer feedback. "
            "You have years of experience identifying patterns in reviews "
            "and understanding customer sentiment and concerns."
        ),
        tools=[analyze_sentiment, extract_keywords, summarize_review],
        verbose=True,
    )

    # Create a task for the agent
    sample_review = (
        "This product is absolutely amazing! The quality is excellent and delivery was fast. "
        "I love the design and the price is reasonable. Great customer service too!"
    )

    analysis_task = Task(
        description=f"Analyze the following review: '{sample_review}'",
        expected_output=(
            "A detailed analysis including sentiment, key themes, and a summary"
        ),
        agent=reviewer_agent,
    )

    # Create a crew with the single agent
    crew = Crew(
        agents=[reviewer_agent],
        tasks=[analysis_task],
        verbose=True,
    )

    # Execute the crew
    result = crew.kickoff()
    print("\n" + "=" * 60)
    print("ANALYSIS RESULT")
    print("=" * 60)
    print(result)


if __name__ == "__main__":
    main()
