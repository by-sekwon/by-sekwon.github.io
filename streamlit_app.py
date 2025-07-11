import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

st.set_page_config(page_title="Onnuri Dashboard", layout="wide")

st.title("📊 Onnuri Gift Certificate Dashboard")

# Define tabs
tabs = st.tabs(["📈 Simulation", "📋 Data Table", "ℹ️ About"])

# --------------------------------
# 📈 Simulation tab
# --------------------------------
with tabs[0]:
    st.subheader("📈 Monthly Transaction Simulation")

    mean_val = st.slider("Average Monthly Transaction (in 100M KRW)", 100, 1000, 500, 50)
    std_val = st.slider("Standard Deviation", 10, 300, 100, 10)

    months = [f"Month {i}" for i in range(1, 13)]
    sim_data = np.random.normal(loc=mean_val, scale=std_val, size=12).clip(min=0)
    df = pd.DataFrame({
        "Month": months,
        "Transaction (100M KRW)": sim_data.astype(int)
    })

    fig, ax = plt.subplots()
    ax.bar(df["Month"], df["Transaction (100M KRW)"], color='skyblue')
    ax.set_title("Simulated Monthly Transactions")
    st.pyplot(fig)

# --------------------------------
# 📋 Data Table tab
# --------------------------------
with tabs[1]:
    st.subheader("📋 Simulation Result Table")
    st.dataframe(df)

# --------------------------------
# ℹ️ About tab
# --------------------------------
with tabs[2]:
    st.subheader("ℹ️ About This Dashboard")
    st.markdown("""
This dashboard simulates monthly transaction volumes for the Onnuri gift certificate.
Use the sliders to adjust the average and variability, and view results in real time.

**Developer**: Prof. Kwon Sehyuk  
**Powered by**: [Streamlit](https://streamlit.io)
    """)