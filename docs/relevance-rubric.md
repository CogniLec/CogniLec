# Relevance Labelling Rubric — LIS S05

## Purpose
Label utterances as **on_topic** or **off_topic** for training/evaluating the A1 Relevance Filter (S41).

## Definitions

### on_topic (Retain)
Content that contributes to the lecture's educational objectives.

| Category | Examples | Notes |
|----------|----------|-------|
| **Core content** | Definitions, explanations, derivations, examples, summaries | Primary lecture material |
| **Relevant student questions** | "What does X mean?", "How does Y relate to Z?", "Is this on the exam?" | Questions about the topic |
| **Clarifications** | "Let me rephrase that", "In other words...", "To clarify..." | Lecturer self-correction |
| **Transitions** | "Now we'll cover...", "Moving on to...", "Before the break..." | Topic boundary signals |
| **References** | "As we saw last week...", "Chapter 3 covers this..." | Cross-references |

### off_topic (Discard)
Content that does not contribute to the lecture's educational objectives.

| Category | Examples | Notes |
|----------|----------|-------|
| **Admin announcements** | "Assignment due Friday", "Exam room changed", "Sign attendance" | Course logistics |
| **Off-topic chatter** | "Did you see the game?", "Lunch menu today", "Weather talk" | Social conversation |
| **Lecturer tangents** | Personal anecdotes unrelated to topic, rants, jokes | Not illustrative of topic |
| **Technical issues** | "Can you hear me?", "Mic check", "Slides not loading" | Meta-commentary |
| **Side conversations** | Students talking among themselves (if captured) | Background noise |

## Edge Cases — Default to **on_topic**

| Situation | Decision | Rationale |
|-----------|----------|-----------|
| Student question, slightly off-topic but shows engagement | **on_topic** | Asymmetric cost: better to keep than discard real engagement |
| Lecturer joke that illustrates concept | **on_topic** | Pedagogical purpose |
| Admin announcement about exam content | **on_topic** | "Exam covers Chapters 1-3" = topic signal |
| Unclear audio / mumbling | **on_topic** | Conservative: don't discard potentially relevant |

## Asymmetric Cost Principle
- **False positive (keep off-topic):** Slightly noisy notes — user can ignore
- **False negative (discard on-topic):** Silently incomplete notes — user cannot detect
- **Target:** Precision on discard > 0.90, Recall on off-topic > 0.80

## Labeling Procedure
1. Read utterance in context (surrounding 2-3 utterances visible in Label Studio)
2. Apply rubric categories above
3. If uncertain → **on_topic** (conservative)
4. Mark "ambiguous" flag if genuinely unsure (for later review)

## Inter-Annotator Agreement
- Target: Cohen's κ ≥ 0.75 on 200-utterance overlap
- If κ < 0.75: Review disagreements, refine rubric, re-label overlap set

## Examples

| Utterance | Label | Reason |
|-----------|-------|--------|
| "The derivative of x squared is 2x." | on_topic | Core content |
| "Does anyone know when the midterm is?" | off_topic | Admin |
| "Wait, so photosynthesis produces oxygen?" | on_topic | Student clarification |
| "By the way, my cat did the funniest thing..." | off_topic | Tangent |
| "This connects to what we covered in Chapter 2." | on_topic | Cross-reference |
| "Can everyone hear me in the back?" | off_topic | Technical |
| "That's a great question — it relates to the next topic." | on_topic | Transition |

---
*This rubric is the source of truth for S05 Project 3 labelling. Update version in DVC if modified.*
