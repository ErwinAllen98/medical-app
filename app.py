import streamlit as st

# تنظیمات ظاهری صفحه
st.set_page_config(page_title="Medical Flashcards", page_icon="🩺")

st.title("🩺 دستیار هوشمند فلش‌کارت پزشکی")
st.write("متن رفرنس یا گایدلاین خود را اینجا قرار دهید تا بر اساس اصل حداقل اطلاعات به کارت تبدیل شود.")

# ۱. کادر ورود متن توسط کاربر
source_text = st.text_area("متن پزشکی (انگلیسی یا فارسی):", height=200)

# ۲. دکمه برای شروع عملیات
if st.button("ساخت فلش‌کارت‌ها"):
    if source_text:
        st.info("به زودی پردازش متن در اینجا انجام می‌شود...")
    else:
        st.warning("لطفاً ابتدا یک متن پزشکی وارد کنید!")
