"""Synthetic lecture transcript generator for testing."""

from __future__ import annotations

import random
from dataclasses import dataclass

from faker import Faker

fake = Faker()


@dataclass
class SyntheticUtterance:
    text: str
    start_ms: int
    end_ms: int
    speaker: str  # "lecturer" or "student"
    is_off_topic: bool = False
    topic_idx: int = 0


@dataclass
class ExpectedSegment:
    start_idx: int
    end_idx: int
    topic: str


@dataclass
class SyntheticTranscript:
    utterances: list[SyntheticUtterance]
    topic_boundaries: list[int]
    topic_labels: list[str]
    expected_segments: list[ExpectedSegment]
    num_topics: int
    total_utterances: int


# Topic templates
TOPICS = [
    (
        "Machine Learning",
        [
            "Today we'll cover supervised learning algorithms",
            "The bias-variance tradeoff is fundamental",
            "Gradient descent optimizes the loss function",
            "Neural networks use backpropagation",
            "Regularization prevents overfitting",
        ],
    ),
    (
        "Data Structures",
        [
            "Binary search trees maintain sorted order",
            "Hash tables provide O(1) average lookup",
            "Graph algorithms traverse node connections",
            "Dynamic programming optimizes recursive problems",
            "Stacks and queues are fundamental structures",
        ],
    ),
    (
        "Linear Algebra",
        [
            "Matrix multiplication follows the distributive property",
            "Eigenvalues reveal transformation characteristics",
            "Vector spaces have dimension and basis",
            "Determinants measure volume scaling",
            "SVD decomposes any matrix into components",
        ],
    ),
]

OFF_TOPIC_PHRASES = [
    "Did you see the game last night?",
    "The cafeteria is closed today",
    "Anyone want to grab coffee after class?",
    "I forgot my charger at home",
    "The deadline got extended to next week",
    "Can someone lend me a pen?",
]


class SyntheticTranscriptGenerator:
    """Generate realistic lecture transcripts for testing."""

    def generate(
        self,
        num_topics: int = 3,
        utterances_per_topic: int = 20,
        include_off_topic: bool = True,
        off_topic_ratio: float = 0.1,
        include_discussion: bool = False,
        seed: int | None = None,
    ) -> SyntheticTranscript:
        """Generate a synthetic transcript."""
        if seed is not None:
            random.seed(seed)

        topics = random.sample(TOPICS, min(num_topics, len(TOPICS)))
        topic_labels = [t[0] for t in topics]
        all_utterances: list[SyntheticUtterance] = []
        topic_boundaries: list[int] = []
        expected_segments: list[ExpectedSegment] = []

        current_ms = 0

        for topic_idx, (topic_name, phrases) in enumerate(topics):
            start_idx = len(all_utterances)
            topic_boundaries.append(start_idx)

            for _ in range(utterances_per_topic):
                # Lecturer speech
                text = random.choice(phrases)
                duration = random.randint(3000, 8000)
                all_utterances.append(
                    SyntheticUtterance(
                        text=text,
                        start_ms=current_ms,
                        end_ms=current_ms + duration,
                        speaker="lecturer",
                        topic_idx=topic_idx,
                    )
                )
                current_ms += duration + random.randint(500, 1500)

                # Optional student discussion
                if include_discussion and random.random() < 0.3:
                    student_text = fake.sentence(nb_words=random.randint(5, 15))
                    duration = random.randint(2000, 5000)
                    all_utterances.append(
                        SyntheticUtterance(
                            text=student_text,
                            start_ms=current_ms,
                            end_ms=current_ms + duration,
                            speaker="student",
                            topic_idx=topic_idx,
                        )
                    )
                    current_ms += duration + random.randint(500, 1000)

                # Off-topic interjection
                if include_off_topic and random.random() < off_topic_ratio:
                    off_text = random.choice(OFF_TOPIC_PHRASES)
                    duration = random.randint(2000, 4000)
                    all_utterances.append(
                        SyntheticUtterance(
                            text=off_text,
                            start_ms=current_ms,
                            end_ms=current_ms + duration,
                            speaker="student",
                            is_off_topic=True,
                            topic_idx=topic_idx,
                        )
                    )
                    current_ms += duration + random.randint(500, 1000)

            end_idx = len(all_utterances) - 1
            expected_segments.append(
                ExpectedSegment(
                    start_idx=start_idx,
                    end_idx=end_idx,
                    topic=topic_name,
                )
            )

        return SyntheticTranscript(
            utterances=all_utterances,
            topic_boundaries=topic_boundaries,
            topic_labels=topic_labels,
            expected_segments=expected_segments,
            num_topics=num_topics,
            total_utterances=len(all_utterances),
        )
