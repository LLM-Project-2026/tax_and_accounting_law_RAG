import streamlit as st

from client import LLMClient, load_secrets
from ui.chat import render


@st.cache_resource
def get_client():
    secrets = load_secrets()
    return LLMClient(
        api_key=secrets["api_key"],
        base_url=secrets["base_url"],
        model=secrets["model"],
    )


def main():
    st.set_page_config(page_title="Chat", page_icon="💬")
    render(get_client())


if __name__ == "__main__":
    main()
