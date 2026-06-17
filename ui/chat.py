import streamlit as st

from prompts.prompts import SYSTEM_PROMPT
from ui.export import chats_to_csv
from rag.retriever import retrieve_context

def _new_chat():
    """Create a fresh chat and make it the current one."""
    st.session_state.chat_counter += 1
    chat_id = st.session_state.chat_counter
    st.session_state.chats.append(
        {
            "id": chat_id,
            "title": "New chat",
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        }
    )
    st.session_state.current_chat_id = chat_id


def _init_state():
    if "chats" not in st.session_state:
        st.session_state.chats = []
        st.session_state.chat_counter = 0
        st.session_state.current_chat_id = None
        _new_chat()


def _current_chat():
    for chat in st.session_state.chats:
        if chat["id"] == st.session_state.current_chat_id:
            return chat
    return st.session_state.chats[0]


def render_sidebar():
    with st.sidebar:
        st.header("Chats")

        for chat in st.session_state.chats:
            label = chat["title"]
            if chat["id"] == st.session_state.current_chat_id:
                label = f"▶ {label}"
            if st.button(label, key=f"chat_{chat['id']}", use_container_width=True):
                st.session_state.current_chat_id = chat["id"]
                st.rerun()

        # Spacer pushes the action buttons toward the bottom of the sidebar.
        st.markdown("<div style='height: 40vh'></div>", unsafe_allow_html=True)

        if st.button("➕ New chat", use_container_width=True):
            _new_chat()
            st.rerun()

        st.download_button(
            "⬇️ Export CSV",
            data=chats_to_csv(st.session_state.chats),
            file_name="chats.csv",
            mime="text/csv",
            use_container_width=True,
        )


def render(client):
    st.title("Chat")
    _init_state()
    render_sidebar()

    chat = _current_chat()

    # Render the current chat's history (skip the system prompt).
    for msg in chat["messages"]:
        if msg["role"] == "system":
            continue
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("Type a message...")
    if not prompt:
        return

    rag_context = retrieve_context(prompt, top_k=3)
    prompt = f"Въз основа на следния контекст: {rag_context}\n\n{prompt}"

    chat["messages"].append({"role": "user", "content": prompt})
    if chat["title"] == "New chat":
        chat["title"] = prompt[:40]
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        reply = st.write_stream(client.chat(chat["messages"]))

    chat["messages"].append({"role": "assistant", "content": reply})
