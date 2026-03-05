import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import os
import json
import re
import unicodedata
import tempfile
import time  # Added time module for API rate limiting
from duckduckgo_search import DDGS
from agno.agent import Agent
from agno.models.google import Gemini
from dotenv import load_dotenv
from fpdf import FPDF

# 1. Base Setup
load_dotenv()
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except:
    api_key = os.getenv("GOOGLE_API_KEY")

st.set_page_config(page_title="FinSight AI Pro", layout="wide")

# 2. UI Styling
st.markdown("""
    <style>
        .block-container { max-width: 98% !important; padding-top: 4rem !important; padding-bottom: 100px !important; padding-left: 1rem !important; padding-right: 1rem !important; }
        [data-testid="stMetric"] { background-color: #1E1E2E; border-radius: 10px; padding: 15px; border: 1px solid #3E3E4E; }
        .ticker-wrap { width: 100%; overflow: hidden; background: #4A90E2; color: white; padding: 12px 0; position: fixed; bottom: 0; left: 0; z-index: 999; }
        .ticker { display: inline-block; white-space: nowrap; animation: ticker 60s linear infinite; font-size: 16px; font-weight: bold; }
        th, td { text-align: left !important; font-size: 16px; }
        @keyframes ticker { 0% { transform: translateX(100%); } 100% { transform: translateX(-100%); } }
    </style>
""", unsafe_allow_html=True)

# 3. Helpers
def clean_for_pdf(text):
    if not text: return ""
    text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode('ascii')
    return "".join(c for c in text if 32 <= ord(c) <= 126)

def calculate_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_sector_benchmark(symbol, sector):
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        nifty = {"Technology": "^CNXIT", "Financial Services": "^NSEBANK", "Healthcare": "^CNXPHARMA", "Consumer Cyclical": "^CNXAUTO"}
        return nifty.get(sector, "^NSEI") 
    else:
        us_etfs = {"Technology": "XLK", "Healthcare": "XLV", "Financial Services": "XLF", "Consumer Cyclical": "XLY", "Industrials": "XLI"}
        return us_etfs.get(sector, "^GSPC") 

# 4. Pro PDF Generator
def generate_pro_pdf(symbol, data, fig_p, fig_l, fig_gauge, fig_comp, comp_ticker=None, comp_data=None):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    pdf.set_font("Helvetica", 'B', 20)
    pdf.cell(180, 15, clean_for_pdf(f"FINSIGHT PRO REPORT: {symbol}"), ln=True, align='C')
    pdf.ln(5)
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(180, 10, clean_for_pdf(f"Price: ${data['price']:.2f} | Sector: {data['fund']['sector']} | Verdict: {data['ai']['verdict']}"), ln=True, align='C')
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t1, \
             tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t2, \
             tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t3:
            
            fig_p.write_image(t1.name, width=800, height=400)
            fig_l.write_image(t2.name, width=800, height=400)
            fig_comp.write_image(t3.name, width=800, height=400)
            
            pdf.image(t1.name, x=15, w=180)
            pdf.image(t2.name, x=15, w=180)
            
            pdf.add_page()
            pdf.set_font("Helvetica", 'B', 14)
            pdf.cell(180, 10, "GROWTH COMPARISON", ln=True, align='C')
            pdf.image(t3.name, x=15, w=180)
            
            if comp_ticker and comp_data:
                pdf.ln(10)
                pdf.set_font("Helvetica", 'B', 14)
                pdf.cell(180, 10, "HEAD-TO-HEAD STATS", ln=True, align='C')
                pdf.ln(5)
                pdf.set_font("Helvetica", 'B', 11)
                
                pdf.cell(60, 10, "Metric", border=1, align='C')
                pdf.cell(60, 10, clean_for_pdf(symbol), border=1, align='C')
                pdf.cell(60, 10, clean_for_pdf(comp_ticker), border=1, align='C', ln=True)
                
                pdf.set_font("Helvetica", '', 11)
                metrics = [
                    ("Sector", data['fund']['sector'], comp_data['fund']['sector']),
                    ("Price", f"${data['price']:.2f}", f"${comp_data['price']:.2f}"),
                    ("Market Cap", data['fund']['mcap'], comp_data['fund']['mcap']),
                    ("P/E Ratio", str(data['fund']['pe']), str(comp_data['fund']['pe'])),
                    ("AI Verdict", data['ai']['verdict'], comp_data['ai']['verdict'])
                ]
                for m, v1, v2 in metrics:
                    pdf.cell(60, 10, clean_for_pdf(m), border=1)
                    pdf.cell(60, 10, clean_for_pdf(v1), border=1, align='C')
                    pdf.cell(60, 10, clean_for_pdf(v2), border=1, align='C', ln=True)

        os.remove(t1.name)
        os.remove(t2.name)
        os.remove(t3.name)
    except: pass

    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 14)
    pdf.cell(180, 10, "AI ANALYSIS", ln=True)
    pdf.set_font("Helvetica", '', 11)
    
    pdf.set_text_color(46, 125, 50)
    pdf.cell(180, 8, "Bullish:", ln=True)
    pdf.set_text_color(0, 0, 0)
    for b in data['ai']['bulls']: pdf.multi_cell(180, 8, clean_for_pdf(f"- {b}"))
    
    pdf.ln(5)
    pdf.set_text_color(211, 47, 47)
    pdf.cell(180, 8, "Bearish:", ln=True)
    pdf.set_text_color(0, 0, 0)
    for b in data['ai']['bears']: pdf.multi_cell(180, 8, clean_for_pdf(f"- {b}"))

    try:
        out = pdf.output()
        return out.encode('latin-1') if isinstance(out, str) else bytes(out)
    except:
        return pdf.output(dest='S').encode('latin-1')

# 5. Data Engine (CACHE REMOVED FOR DEBUGGING)
def fetch_analysis(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="3y")
        if df.empty: return None
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['RSI'] = calculate_rsi(df['Close'])
        curr_p = df['Close'].iloc[-1]
        
        info = ticker.info
        mcap = info.get('marketCap', 0)
        pe = info.get('trailingPE', 'N/A')
        sector = info.get('sector', 'Market')
        
        def fmt(n):
            if not isinstance(n, (int, float)) or n == 0: return "N/A"
            if n >= 1e12: return f"{n/1e12:.2f}T"
            if n >= 1e9: return f"{n/1e9:.2f}B"
            return f"{n/1e6:.2f}M"
        fund = {"mcap": f"${fmt(mcap)}", "pe": round(pe, 2) if isinstance(pe, (int, float)) else pe, "sector": sector}

        fin_data = None
        try:
            inc = ticker.income_stmt
            if not inc.empty:
                rev_key = next((k for k in ['Total Revenue', 'Operating Revenue'] if k in inc.index), None)
                net_key = next((k for k in ['Net Income', 'Net Income Common Stockholders'] if k in inc.index), None)
                if rev_key and net_key:
                    rev = inc.loc[rev_key].dropna()[:3][::-1]
                    net = inc.loc[net_key].dropna()[:3][::-1]
                    dates = [d.strftime('%Y') for d in rev.index]
                    fin_data = {"dates": dates, "revenue": rev.tolist(), "net_income": net.tolist()}
        except: pass

        # --- AI LOGIC WITH DEBUG OUTPUT ---
        raw_content = ""
        try:
            agent = Agent(model=Gemini(id="gemini-2.0-flash", api_key=api_key))
            prompt = f"""You are a data analyzer. Analyze {symbol} in the {sector} sector based on general market trends.
            Respond strictly with a JSON object and no other text.
            Format EXACTLY like this: {{"bulls": ["Point 1", "Point 2", "Point 3"], "bears": ["Point 1", "Point 2", "Point 3"], "verdict": "BUY", "score": 85}}"""
            
            resp = agent.run(prompt)
            raw_content = str(resp.content) if hasattr(resp, 'content') else str(resp)
            
            # Uncomment this if you still want to see the raw output
            # st.info(f"🔍 DEBUG - Raw AI Output for {symbol}: {raw_content}")
            
            clean_json = raw_content.replace('```json', '').replace('```', '').strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            
            if match:
                ai_json = json.loads(match.group())
            else:
                ai_json = json.loads(clean_json)
                
        except Exception as e:
            st.error(f"🚨 API Parsing Error for {symbol}: {str(e)}")
            ai_json = {}
        # -------------------------------

        bulls = ai_json.get('bulls', [])
        if not isinstance(bulls, list) or len(bulls) < 3:
            bulls = ["Strong market position.", "Positive revenue trends.", "Solid technical support."]
            
        bears = ai_json.get('bears', [])
        if not isinstance(bears, list) or len(bears) < 3:
            bears = ["Macroeconomic volatility.", "Sector headwinds.", "Profit-taking resistance."]
            
        verdict = str(ai_json.get('verdict', 'HOLD')).upper()
        if not verdict or verdict == 'N/A' or verdict not in ['BUY', 'HOLD', 'SELL', 'STRONG BUY', 'STRONG SELL']:
            verdict = 'HOLD'

        score = ai_json.get('score', 50)
        if not isinstance(score, (int, float)):
            score = 50

        ai_data = {"bulls": bulls, "bears": bears, "verdict": verdict, "score": score}
        return {"df": df, "price": curr_p, "fund": fund, "ai": ai_data, "fin_data": fin_data}
    except Exception as e: 
        st.error(f"Data Fetch Error: {str(e)}")
        return None

# 6. Sidebar
with st.sidebar:
    st.title("📊 FinSight AI")
    main_ticker = st.text_input("Main Stock (e.g. NVDA):").upper()
    comp_ticker = st.text_input("Compare with (Optional):", placeholder="e.g. AAPL").upper()
    run = st.button("🚀 Run Analysis", use_container_width=True)

# 7. Rendering Logic
if run and main_ticker:
    with st.spinner("Analyzing main stock intelligence..."):
        data = fetch_analysis(main_ticker)
        
    comp_data = None
    if comp_ticker and comp_ticker != main_ticker:
        # Added delay here to prevent API rate limiting
        st.warning(f"⏳ Waiting 5 seconds before analyzing {comp_ticker} to avoid API Rate Limits...")
        time.sleep(5)
        with st.spinner(f"Analyzing {comp_ticker} intelligence..."):
            comp_data = fetch_analysis(comp_ticker)

    if data:
        cols = st.columns(5)
        cols[0].metric("Stock", main_ticker)
        cols[1].metric("Sector", data['fund']['sector'])
        cols[2].metric("Price", f"${data['price']:.2f}")
        cols[3].metric("Market Cap", data['fund']['mcap'])
        cols[4].metric("Verdict", data['ai']['verdict'])
        st.markdown("---")
        
        st.subheader("📈 Intelligence Charts")
        c1, c2 = st.columns(2)
        with c1:
            fig_p = go.Figure()
            fig_p.add_trace(go.Scatter(x=data['df'].index, y=data['df']['Close'], name='Price', line=dict(color='#00FF00')))
            fig_p.add_trace(go.Scatter(x=data['df'].index, y=data['df']['SMA_50'], name='50 SMA', line=dict(dash='dot', color='orange')))
            fig_p.update_layout(height=350, title="Price Action", template="plotly_dark")
            st.plotly_chart(fig_p, use_container_width=True)
        with c2:
            fig_l = go.Figure(go.Scatter(x=data['df'].index, y=data['df']['Low'], line=dict(color='red')))
            fig_l.update_layout(height=350, title="Risk Trend (Lows)", template="plotly_dark", yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_l, use_container_width=True)

        st.markdown("---")
        m_col, g_col = st.columns(2)
        with m_col:
            st.markdown("<h4 style='text-align: center;'>🧠 AI Sentiment Meter</h4>", unsafe_allow_html=True)
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number", value = data['ai']['score'],
                gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "#4A90E2"},
                         'steps' : [{'range': [0, 30], 'color': "red"}, {'range': [30, 70], 'color': "yellow"}, {'range': [70, 100], 'color': "green"}]}
            ))
            fig_gauge.update_layout(height=250, margin=dict(t=30, b=0), template="plotly_dark")
            st.plotly_chart(fig_gauge, use_container_width=True)
            
        with g_col:
            target_label = comp_ticker if comp_data else f"{data['fund']['sector']} Benchmark"
            st.markdown(f"<h4 style='text-align: center;'>⚔️ Growth Comparison</h4>", unsafe_allow_html=True)
            fig_comp = go.Figure()
            fig_comp.add_trace(go.Scatter(x=data['df'].index, y=(data['df']['Close'] / data['df']['Close'].iloc[0] - 1) * 100, name=main_ticker, line=dict(color='#00FF00')))
            try:
                if comp_data:
                    c_df = comp_data['df']
                else:
                    c_df = yf.Ticker(get_sector_benchmark(main_ticker, data['fund']['sector'])).history(period="3y")
                
                if not c_df.empty:
                    fig_comp.add_trace(go.Scatter(x=c_df.index, y=(c_df['Close'] / c_df['Close'].iloc[0] - 1) * 100, name=target_label, line=dict(color='#1E90FF')))
            except: pass
            fig_comp.update_layout(height=250, margin=dict(t=30, b=0), template="plotly_dark", yaxis_title="Growth %")
            st.plotly_chart(fig_comp, use_container_width=True)

        # Head-to-Head Section
        if comp_data:
            st.markdown("---")
            st.subheader(f"🥊 Head-to-Head: {main_ticker} vs {comp_ticker}")
            st.markdown(f"""
            | Metric | {main_ticker} | {comp_ticker} |
            | :--- | :--- | :--- |
            | **Sector** | {data['fund']['sector']} | {comp_data['fund']['sector']} |
            | **Current Price** | ${data['price']:.2f} | ${comp_data['price']:.2f} |
            | **Market Cap** | {data['fund']['mcap']} | {comp_data['fund']['mcap']} |
            | **P/E Ratio** | {data['fund']['pe']} | {comp_data['fund']['pe']} |
            | **AI Verdict** | {data['ai']['verdict']} | {comp_data['ai']['verdict']} |
            | **Sentiment Score** | {data['ai']['score']}/100 | {comp_data['ai']['score']}/100 |
            """)

        if data.get('fin_data'):
            st.markdown("---")
            st.subheader("💰 Income Statement Highlights (Last 3 Years)")
            fig_fin = go.Figure()
            fig_fin.add_trace(go.Bar(x=data['fin_data']['dates'], y=data['fin_data']['revenue'], name='Revenue', marker_color='#4A90E2'))
            fig_fin.add_trace(go.Bar(x=data['fin_data']['dates'], y=data['fin_data']['net_income'], name='Net Income', marker_color='#00FF00'))
            fig_fin.update_layout(barmode='group', height=300, template="plotly_dark", margin=dict(t=30, b=0))
            st.plotly_chart(fig_fin, use_container_width=True)

        st.markdown("---")
        i1, i2 = st.columns(2)
        with i1:
            st.success("**🐂 Bullish Insights:**")
            for b in data['ai']['bulls']: st.write(f"✅ {b}")
        with i2:
            st.error("**🐻 Bearish Risks:**")
            for b in data['ai']['bears']: st.write(f"⚠️ {b}")

        st.markdown("---")
        d1, d2 = st.columns(2)
        with d1:
            st.download_button("📥 Download Pro PDF Report", generate_pro_pdf(main_ticker, data, fig_p, fig_l, fig_gauge, fig_comp, comp_ticker, comp_data), f"{main_ticker}_Report.pdf", use_container_width=True)
        with d2:
            st.download_button("📊 Export CSV Data", data['df'].to_csv().encode('utf-8'), f"{main_ticker}.csv", use_container_width=True)
    else: st.error("Sync Failed. Check symbol.")
else:
    st.markdown("<h1 style='text-align: center; margin-top: 15vh; color: #4A90E2;'>📊 FinSight AI Pro</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 1.2rem; color: #A0A0A0;'>Enter a stock ticker to start your analysis.</p>", unsafe_allow_html=True)
