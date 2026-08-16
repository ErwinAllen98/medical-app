import streamlit as st
import google.generativeai as genai

# Page configuration
st.set_page_config(page_title="Medical Flashcards", page_icon="🩺")

# Attempt to retrieve the key from Secrets and configure the model
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-pro")
except Exception as e:
    st.error("🚨 Connection to Secrets failed! Did you save the key in the Secrets section?")

st.title("🩺 Smart Medical Flashcard Assistant")
st.write("Paste your medical reference or guideline here to convert it into flashcards based on the Minimum Information Principle.")

source_text = st.text_area("Medical Text (English or Persian):", height=200)

if st.button("Generate Flashcards"):
    if source_text:
        with st.spinner("Processing text and generating cards... ⏳"):
            # Prompt given to the AI
            prompt = f"""
            You are a medical education expert. Read the following text and convert it into short, individual flashcards based on the 'Minimum Information Principle'.
            Provide the output strictly as a Markdown table with two columns (Column 1: Question, Column 2: Answer).
            Text:
            {source_text}
            """
            
            # Send the prompt and get the response
            response = model.generate_content(prompt)
            st.markdown(response.text)
    else:
        st.warning("Please enter some medical text first!")
