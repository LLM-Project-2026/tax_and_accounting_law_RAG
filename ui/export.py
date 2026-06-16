import pandas as pd


def chats_to_csv(chats):
    """Export all chats' history to a wide-format CSV string.

    One row per chat. Each turn becomes its own pair of columns:
    user_1, assistant_1, user_2, assistant_2, ...
    Shorter chats are padded with empty cells.
    """
    rows = []
    max_turns = 0

    for chat in chats:
        row = {}
        turn = 0
        for msg in chat["messages"]:
            if msg["role"] == "user":
                turn += 1
                row[f"user_{turn}"] = msg["content"]
            elif msg["role"] == "assistant":
                row[f"assistant_{turn}"] = msg["content"]
        max_turns = max(max_turns, turn)
        rows.append(row)

    # Build an ordered, padded column list so every chat lines up.
    columns = []
    for t in range(1, max_turns + 1):
        columns.extend([f"user_{t}", f"assistant_{t}"])

    df = pd.DataFrame(rows, columns=columns).fillna("")
    return df.to_csv(index=False)
