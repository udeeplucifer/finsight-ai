import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import os
import json
import re
import unicodedata
import tempfile
from duckduckgo_search import DDGS
from agno.agent import Agent
from agno.models.google import Gemini
from dotenv import load_dotenv
from fpdf import FPDF

# 1. Base Setup & Cloud API Key Logic
load_dotenv()
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except Exception:
    api_key = os.getenv("GOOGLE_API_KEY")

st.set_page_config(page_title="FinSight AI", layout="wide")

# 2. UI & News Ticker CSS
st.markdown("""
    <style>
        .block-container { max-width: 98% !important; padding: 1rem !important; padding-bottom: 80px !important; }
        div[data-testid="metric-container"] { background-color: #1E1E2E; border-radius: 10px; padding: 15px; text-align: center; }
        .ticker-wrap { width: 100%; overflow: hidden; background: #4A90E2; color: white; padding: 12px 0; position: fixed; bottom: 0; left: 0; z-index: 999; }
        .ticker { display: inline-block; white-space: nowrap; animation: ticker 60s linear infinite; font-size: 16px; font-weight: bold; }
        @keyframes ticker { 0% { transform: translateX(100%); } 100% { transform: translateX(-100%); } }
    </style>
""", unsafe_allow_html=True)

# 3. Enhanced Character Cleaner for PDF
def clean_for_pdf(text):
    if not text: return ""
    text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode('ascii')
    return "".join(c for c in text if 32 <= ord(c) <= 126)

# 4. Premium PDF Generator (Safe for both FPDF1 & FPDF2)
def generate_pdf(symbol, data, fig1, fig2):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    
    pdf.set_font("Helvetica", 'B', 20)
    pdf.cell(180, 15, clean_for_pdf(f"FINSIGHT AI REPORT: {symbol}"), ln=True, align='C')
    pdf.ln(5)
    
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(180, 10, clean_for_pdf(f"Price: ${data['price']:.2f} | Growth: {data['growth']:.2f}% | Verdict: {data['verdict']}"), ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Helvetica", 'B', 14)
    pdf.set_text_color(46, 125, 50)
    pdf.cell(180, 10, "BULLISH INSIGHTS", ln=True)
    pdf.set_font("Helvetica", '', 11)
    pdf.set_text_color(0, 0, 0)
    for p in data['bulls_list']:
        pdf.set_x(15)
        pdf.multi_cell(180, 8, clean_for_pdf(f"- {p}"))
    pdf.ln(5)

    pdf.set_font("Helvetica", 'B', 14)
    pdf.set_text_color(211, 47, 47)
    pdf.cell(180, 10, "BEARISH RISKS", ln=True)
    pdf.set_font("Helvetica", '', 11)
    pdf.set_text_color(0, 0, 0)
    for p in data['bears_list']:
        pdf.set_x(15)
        pdf.multi_cell(180, 8, clean_for_pdf(f"- {p}"))
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t1, \
             tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t2:
            fig1.write_image(t1.name, width=800, height=400)
            fig2.write_image(t2.name, width=800, height=400)
            pdf.add_page()
            pdf.set_font("Helvetica", 'B', 14)
            pdf.cell(180, 10, "PROFIT TREND & SMA", ln=True, align='C')
            pdf.image(t1.name, x=15, w=180)
            pdf.ln(5)
            pdf.cell(180, 10, "LOSS TREND (LOWS)", ln=True, align='C')
            pdf.image(t2.name, x=15, w=180)
        os.remove(t1.name)
        os.remove(t2.name)
    except Exception:
        pass

    # Safe Return for different FPDF versions
    try:
        out = pdf.output()
        if isinstance(out, str):
            return out.encode('latin-1')
        return bytes(out)
    except Exception:
        return pdf.output(dest='S').encode('latin-1')

# 5. Core Data Sync Logic with Error Debugging
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_analysis(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="3y")
        if df.empty: return None
        
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        curr_p = df['Close'].iloc[-1]
        gr = ((curr_p - df['Close'].iloc[0]) / df['Close'].iloc[0]) * 100

        try:
            info = ticker.info
            mcap = info.get('marketCap', 0)
            pe = info.get('trailingPE', 'N/A')
            
            def fmt(n):
                if not isinstance(n, (int, float)) or n == 0: return "N/A"
                if n >= 1e12: return f"{n/1e12:.2f}T"
                if n >= 1e9: return f"{n/1e9:.2f}B"
                if n >= 1e6: return f"{n/1e6:.2f}M"
                return str(n)
                
            fund_data = {
                "mcap": f"${fmt(mcap)}" if fmt(mcap) != "N/A" else "N/A",
                "pe": round(pe, 2) if isinstance(pe, (int, float)) else pe
            }
        except:
            fund_data = {"mcap": "N/A", "pe": "N/A"}

        news = []
        try:
            with DDGS() as ddgs:
                res = list(ddgs.news(symbol, max_results=5))
                news = [n['title'] for n in res]
        except: news = ["Market volatility analysis active."]

        agent = Agent(model=Gemini(id="gemini-2.0-flash", api_key=api_key))
        prompt = f"Analyze {symbol} (Price: {curr_p}). News: {news}. Return ONLY JSON with 'bulls' and 'bears' as LISTS of 2 points, and 'verdict'."
        resp = agent.run(prompt)
        match = re.search(r'\{.*\}', resp.content.strip(), re.DOTALL)
        ai_json = json.loads(match.group())

        return {
            "df": df, "price": curr_p, "growth": gr, "news": news, "fund": fund_data,
            "bulls_list": ai_json.get("bulls", ["Positive momentum.", "Stable growth."]),
            "bears_list": ai_json.get("bears", ["Market risks.", "Global uncertainty."]),
            "verdict": str(ai_json.get("verdict", "HOLD"))
        }
    except Exception as e:
        st.error(f"🔍 System Error: {str(e)}")
        return None

# 6. Sidebar Controls
with st.sidebar:
    st.markdown("<h2 style='color: #4A90E2;'>📊 FinSight AI</h2>", unsafe_allow_html=True)
    st.markdown("---")
    s_code = st.text_input("Main Stock (e.g. RELIANCE.NS, TSLA):").upper()
    compare_code = st.text_input("Compare with (Optional):", placeholder="e.g. AAPL").upper()
    run = st.button("🚀 Generate Full Report", use_container_width=True)

# 7. Rendering Logic
if run and s_code:
    d = fetch_analysis(s_code)
    if d:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Stock", s_code)
        m2.metric("Price", f"${d['price']:.2f}")
        m3.metric("Market Cap", d['fund']['mcap'])
        m4.metric("P/E Ratio", d['fund']['pe'])
        m5.metric("Verdict", d['verdict'])
        
        st.markdown("---")
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("📈 **Profit Trend & Moving Averages**")
            fig_profit = go.Figure()
            fig_profit.add_trace(go.Scatter(x=d['df'].index, y=d['df']['High'], name='Price', line=dict(color='#00FF00', width=2)))
            fig_profit.add_trace(go.Scatter(x=d['df'].index, y=d['df']['SMA_50'], name='50 SMA', line=dict(color='#FFA500', width=1, dash='dot')))
            fig_profit.add_trace(go.Scatter(x=d['df'].index, y=d['df']['SMA_200'], name='200 SMA', line=dict(color='#1E90FF', width=1, dash='dot')))
            fig_profit.update_layout(height=280, margin=dict(l=0,r=0,t=0,b=0), template="plotly_dark", showlegend=True, legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
            st.plotly_chart(fig_profit, use_container_width=True)
            
        with c2:
            st.markdown("📉 **Loss Trend (Lows)**")
            fig_loss = go.Figure(go.Scatter(x=d['df'].index, y=d['df']['Low'], line=dict(color='#FF0000', width=2)))
            fig_loss.update_layout(height=280, margin=dict(l=0,r=0,t=0,b=0), template="plotly_dark", yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_loss, use_container_width=True)

        if compare_code:
            if compare_code == s_code:
                st.warning(f"⚠️ Comparison stock cannot be the same as the main stock ({s_code}). Please enter a different symbol.")
            else:
                st.markdown(f"---")
                st.markdown(f"⚔️ **Growth Comparison: {s_code} vs {compare_code}**")
                with st.spinner(f"Fetching data for {compare_code}..."):
                    try:
                        df_comp = yf.Ticker(compare_code).history(period="3y")

