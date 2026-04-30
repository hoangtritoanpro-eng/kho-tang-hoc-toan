import streamlit as st
import pandas as pd
import json
import uuid
import re
import os
import requests
import google.generativeai as genai
from collections import Counter

# --- Cấu hình API AI ---
# Bạn hãy thay 'YOUR_API_KEY' bằng API Key lấy từ Google AI Studio nhé
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY"))

FIREBASE_URL = os.environ.get("FIREBASE_URL", "https://console.firebase.google.com/project/kho-tang-hoc/database/kho-tang-hoc-default-rtdb/data/~2F")

# --- Cấu hình trang ---
st.set_page_config(page_title="Kho Tàng Học", page_icon="📖", layout="centered")

# --- 1. HÀM LƯU TRỮ (FIREBASE) ---
def save_quiz(quiz_data):
    quiz_id = str(uuid.uuid4().hex)[:6].upper()
    try:
        requests.put(f"{FIREBASE_URL}/quizzes/{quiz_id}.json", json=quiz_data)
    except Exception as e:
        print(f"Lỗi khi lưu quiz: {e}")
    return quiz_id

def load_quiz(quiz_id):
    try:
        res = requests.get(f"{FIREBASE_URL}/quizzes/{quiz_id}.json")
        if res.status_code == 200 and res.json() is not None:
            return res.json()
        return None
    except Exception as e:
        print(f"Lỗi khi tải quiz: {e}")
        return None

def save_result(quiz_id, name, lop, score, wrong_answers):
    lb = load_leaderboard(quiz_id) or []
    lb.append({"Tên": name, "Lớp": lop, "Điểm": score, "Lỗi sai": wrong_answers})
    try:
        requests.put(f"{FIREBASE_URL}/leaderboards/{quiz_id}.json", json=lb)
    except Exception as e:
        print(f"Lỗi khi lưu kết quả: {e}")

def load_leaderboard(quiz_id):
    try:
        res = requests.get(f"{FIREBASE_URL}/leaderboards/{quiz_id}.json")
        if res.status_code == 200 and res.json() is not None:
            return res.json()
        return None
    except Exception as e:
        print(f"Lỗi khi tải bảng xếp hạng: {e}")
        return None

# --- 2. KHỞI TẠO STATE ---
if 'active_quiz_id' not in st.session_state: st.session_state.active_quiz_id = None
if 'student_name' not in st.session_state: st.session_state.student_name = ""
if 'student_class' not in st.session_state: st.session_state.student_class = ""
if 'quiz_data' not in st.session_state: st.session_state.quiz_data = []
if 'current_q' not in st.session_state: st.session_state.current_q = 0
if 'score' not in st.session_state: st.session_state.score = 0
if 'show_explanation' not in st.session_state: st.session_state.show_explanation = False
if 'wrong_answers' not in st.session_state: st.session_state.wrong_answers = []

# Đọc ID từ URL nếu có
query_params = st.query_params
if "id" in query_params:
    st.session_state.active_quiz_id = query_params["id"]

# --- 3. CSS & AUDIO HELPERS ---
def inject_custom_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap');
        html, body, [class*="css"], p, span, div, h1, h2, h3, label { font-family: 'Nunito', sans-serif; }
        .stApp { background-color: #F8FAFC; background-image: radial-gradient(#CBD5E1 1px, transparent 1px); background-size: 24px 24px; }
        
        /* Tông màu Xanh Mint thanh lịch */
        h1, h2, h3 { color: #047857 !important; font-weight: 800 !important; }
        .stProgress > div > div > div { background-image: linear-gradient(to right, #34D399, #10B981); border-radius: 10px; }
        
        /* KaTeX Fix */
        .katex { font-size: 1.25em !important; color: #1D4ED8 !important; line-height: normal !important; }
        .katex * { font-family: inherit; }
        .katex-display { margin: 1em 0 !important; }
        
        /* UI Trắc nghiệm */
        .stRadio label { background: #F1F5F9; padding: 15px; border-radius: 12px; border: 2px solid transparent; transition: all 0.2s; cursor: pointer; align-items: center !important; margin-bottom: 8px; }
        .stRadio label:hover { background: #D1FAE5; border: 2px solid #10B981; }
        div.stButton > button { border-radius: 12px; font-weight: 800; transition: all 0.3s; }
        </style>
    """, unsafe_allow_html=True)

def play_sound(is_correct):
    sound_url = "https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg" if is_correct else "https://actions.google.com/sounds/v1/cartoon/cartoon_boing.ogg"
    st.markdown(f'<audio autoplay="true" src="{sound_url}"></audio>', unsafe_allow_html=True)

inject_custom_css()

# --- 4. TRÌNH BIÊN DỊCH MARKDOWN (ĐÃ FIX LỖI) ---
def parse_markdown_quiz(md_content):
    # Tự động làm to phân số Toán học
    md_content = md_content.replace(r'\frac', r'\dfrac')
    quiz_data = []
    
    # Cắt khối văn bản dựa trên chữ "Câu" hoặc "- Câu hỏi"
    blocks = re.split(r'(?m)^[-*\s]*(?:\*\*|### )?Câu', md_content)
    
    for block in blocks:
        if not block.strip():
            continue
            
        # Xóa các dấu in đậm để dễ đọc
        block = block.replace('**', '')
        
        question = ""
        options = []
        answer = ""
        explanation = "Không có giải thích chi tiết."
        
        # 1. Tách phần thân câu hỏi (Từ đầu đến trước chữ "A.")
        q_split = re.split(r'\bA\.', block, 1)
        if len(q_split) > 1:
            # Lấy tiêu đề câu hỏi (xóa bỏ chữ "hỏi:" hoặc số thứ tự "1:")
            question = re.sub(r'^(?:hỏi)?\s*\d*:\s*', '', q_split[0]).strip()
            rest_of_block = 'A.' + q_split[1]
        else:
            continue # Nếu câu này không có đáp án A., bỏ qua
            
        # 2. Tìm các lựa chọn A, B, C, D (Cho phép nằm trên cùng 1 dòng)
        opt_a = re.search(r'\bA\.(.*?)(?=\bB\.|Đáp\s*án:|Giải\s*thích:|$)', rest_of_block, re.DOTALL)
        opt_b = re.search(r'\bB\.(.*?)(?=\bC\.|Đáp\s*án:|Giải\s*thích:|$)', rest_of_block, re.DOTALL)
        opt_c = re.search(r'\bC\.(.*?)(?=\bD\.|Đáp\s*án:|Giải\s*thích:|$)', rest_of_block, re.DOTALL)
        opt_d = re.search(r'\bD\.(.*?)(?=Đáp\s*án:|Giải\s*thích:|$)', rest_of_block, re.DOTALL)
        
        if opt_a: options.append(opt_a.group(1).strip())
        if opt_b: options.append(opt_b.group(1).strip())
        if opt_c: options.append(opt_c.group(1).strip())
        if opt_d: options.append(opt_d.group(1).strip())
        
        # 3. Trích xuất Đáp án đúng
        ans_match = re.search(r'Đáp\s*án:\s*([A-D])', rest_of_block, re.IGNORECASE)
        if ans_match:
            ans_char = ans_match.group(1).upper()
            idx = ord(ans_char) - 65
            if 0 <= idx < len(options):
                answer = options[idx]
                
        # 4. Trích xuất Giải thích
        exp_match = re.search(r'Giải\s*thích:(.*?)$', rest_of_block, re.DOTALL | re.IGNORECASE)
        if exp_match:
            explanation = exp_match.group(1).strip()
            
        # Kiểm tra hợp lệ (Có câu hỏi và ít nhất 2 đáp án)
        if question and len(options) >= 2:
            # Nếu người dùng quên ghi "Đáp án: X", tạm lấy đáp án đầu tiên làm mốc để không bị lỗi ứng dụng
            if not answer:
                answer = options[0] 
                
            quiz_data.append({
                "question": question,
                "options": options,
                "answer": answer,
                "explanation": explanation
            })
            
    return quiz_data

# --- 5. HÀM GỌI AI SINH ĐỀ ---
def generate_quiz_from_ai(chu_de, muc_do, so_luong=5):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Tạo {so_luong} câu hỏi trắc nghiệm Toán học chủ đề: {chu_de}, mức độ: {muc_do}.
        BẮT BUỘC trả về đúng định dạng Markdown sau, không thêm bất kỳ chữ nào khác:
        
        Câu 1: [Nội dung câu hỏi]
        A. [Đáp án A]
        B. [Đáp án B]
        C. [Đáp án C]
        D. [Đáp án D]
        Đáp án: [A, B, C hoặc D]
        Giải thích: [Giải thích ngắn gọn]
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Lỗi kết nối AI: {e}")
        return None

# --- 6. LUỒNG GIAO DIỆN CHÍNH ---

# LUỒNG A: CHƯA VÀO PHÒNG THI (MÀN HÌNH CHÍNH)
if not st.session_state.active_quiz_id:
    st.title("📖 Kho Tàng Học - Nền Tảng Trắc Nghiệm")
    tab_hs, tab_gv, tab_tk = st.tabs(["🎓 Cổng Học Sinh", "👨‍🏫 Cổng Giáo Viên", "📊 Thống Kê"])
    
    # ---------------- TAB 1: HỌC SINH ----------------
    with tab_hs:
        st.subheader("Nhập mã phòng để bắt đầu")
        room_code = st.text_input("Mã Game (Quiz ID):").strip().upper()
        if st.button("🚪 Vào Phòng", type="primary"):
            if load_quiz(room_code):
                st.session_state.active_quiz_id = room_code
                st.rerun()
            else:
                st.error("Mã phòng không tồn tại!")

    # ---------------- TAB 2: GIÁO VIÊN ----------------
    with tab_gv:
        st.markdown("### Tạo Đề Mới")
        create_mode = st.radio("Phương thức tạo đề:", ["🤖 Nhờ AI tự động", "📝 Dán mã Markdown"])
        
        data = None # Biến tạm lưu dữ liệu quiz
        
        if create_mode == "🤖 Nhờ AI tự động":
            chu_de = st.text_input("Nhập chủ đề Toán học (VD: Lượng giác lớp 10):")
            muc_do = st.selectbox("Mức độ:", ["Dễ", "Trung bình", "Khó"])
            if st.button("✨ Nhờ AI Sinh Đề & Lấy Link", type="primary"):
                if chu_de:
                    with st.spinner("Đang nhờ AI biên soạn đề thi..."):
                        md_content = generate_quiz_from_ai(chu_de, muc_do)
                        if md_content:
                            data = parse_markdown_quiz(md_content)
                else:
                    st.warning("Vui lòng nhập chủ đề!")
                    
        else: # Tự nhập Markdown
            manual_md = st.text_area("Dán mã Markdown bộ câu hỏi vào đây:", height=200)
            if st.button("🚀 Xây Dựng Quiz Từ Text & Lấy Link", type="primary"):
                if manual_md:
                    data = parse_markdown_quiz(manual_md)
                else:
                    st.warning("Vui lòng dán nội dung Markdown!")
        
        # Xử lý sau khi tạo thành công (Chung cho cả AI và Tự nhập)
        if data is not None:
            if len(data) > 0:
                quiz_id = save_quiz(data)
                st.success("🎉 Tạo đề thành công!")
                st.info(f"MÃ GAME CỦA BẠN: **{quiz_id}**")
                
                # Tạo link chia sẻ
                st.code(f"Link truy cập nhanh: http://localhost:8501/?id={quiz_id}")
                
                st.divider()
                st.subheader("👀 Bản Trình Chiếu Xem Trước Đề Thi")
                for i, q in enumerate(data):
                    with st.expander(f"Câu {i+1}: {q['question']}", expanded=False):
                        for opt in q['options']:
                            if opt == q['answer']: st.success(f"✅ **{opt}**")
                            else: st.markdown(f"- {opt}")
                        st.info(f"💡 Giải thích: {q['explanation']}")
            else:
                st.error("Không tìm thấy câu hỏi hợp lệ. Hãy kiểm tra lại định dạng!")

    # ---------------- TAB 3: THỐNG KÊ ----------------
    with tab_tk:
        st.subheader("📈 Phân Tích Kết Quả & Lỗi Sai")
        stat_id = st.text_input("Nhập Mã Game để xem thống kê:").strip().upper()
        if st.button("Xem Thống Kê"):
            lb = load_leaderboard(stat_id)
            if lb:
                st.markdown("### 🏆 Bảng Xếp Hạng")
                df_scores = pd.DataFrame([{"Tên": d["Tên"], "Lớp": d["Lớp"], "Điểm": d["Điểm"]} for d in lb])
                st.dataframe(df_scores.sort_values(by="Điểm", ascending=False), use_container_width=True)
                
                st.markdown("### ⚠️ Phân Tích Các Câu Hay Sai")
                all_wrong = [f"Câu {w['q_num']}: {w['question']}" for s in lb for w in s.get("Lỗi sai", [])]
                if all_wrong:
                    for q, count in Counter(all_wrong).most_common():
                        st.error(f"**{count} học sinh sai** - {q}")
                else:
                    st.success("Tuyệt vời! Không có học sinh nào trả lời sai.")
            else:
                st.warning("Chưa có dữ liệu cho Mã Game này.")

# LUỒNG B: TRONG PHÒNG THI (HỌC SINH LÀM BÀI)
else:
    # Nạp dữ liệu quiz
    if not st.session_state.quiz_data:
        st.session_state.quiz_data = load_quiz(st.session_state.active_quiz_id)
        
    # Bước 1: Báo danh
    if not st.session_state.student_name or not st.session_state.student_class:
        st.title("👋 Chào mừng bạn!")
        st.info("Hãy cho biết bạn là ai trước khi bắt đầu bài thi nhé.")
        name_input = st.text_input("Họ và Tên của bạn:")
        class_input = st.text_input("Lớp (VD: 8/5):")
        if st.button("🚀 Bắt Đầu Chơi", type="primary"):
            if name_input and class_input:
                st.session_state.student_name = name_input
                st.session_state.student_class = class_input
                st.rerun()
            else:
                st.warning("Vui lòng điền đầy đủ thông tin!")
    
    # Bước 2: Chơi Quiz
    else:
        q_idx = st.session_state.current_q
        total = len(st.session_state.quiz_data)
        
        if q_idx < total:
            curr = st.session_state.quiz_data[q_idx]
            st.markdown(f"### Câu {q_idx+1}/{total}")
            st.progress((q_idx+1)/total)
            st.write(curr["question"])
            
            # Khóa lựa chọn nếu đã bấm kiểm tra
            choice = st.radio("Chọn đáp án:", curr["options"], index=None, key=f"q_{q_idx}", disabled=st.session_state.show_explanation)
            
            col1, col2 = st.columns(2)
            if col1.button("🔥 Kiểm Tra", use_container_width=True, type="primary"):
                if choice: st.session_state.show_explanation = True
                else: st.warning("Hãy chọn một đáp án!")
                
            if col2.button("🚪 Thoát Game", use_container_width=True):
                # Lưu điểm trước khi thoát
                save_result(st.session_state.active_quiz_id, st.session_state.student_name, st.session_state.student_class, st.session_state.score, st.session_state.wrong_answers)
                # Reset trạng thái
                for key in ['active_quiz_id', 'student_name', 'student_class', 'quiz_data', 'current_q', 'score', 'show_explanation', 'wrong_answers']:
                    del st.session_state[key]
                st.rerun()
                
            if st.session_state.show_explanation:
                if choice == curr["answer"]:
                    if f"sc_{q_idx}" not in st.session_state:
                        play_sound(True); st.session_state.score += 1; st.session_state[f"sc_{q_idx}"] = True
                    st.success("Chính xác! 🎉")
                else:
                    if f"sc_{q_idx}" not in st.session_state:
                        play_sound(False)
                        st.session_state.wrong_answers.append({
                            "q_num": q_idx + 1, "question": curr["question"], "wrong_choice": choice, 
                            "correct_answer": curr["answer"], "explanation": curr["explanation"]
                        })
                        st.session_state[f"sc_{q_idx}"] = True
                    st.error(f"Sai rồi! Đáp án đúng là: {curr['answer']}")
                st.info(f"💡 Giải thích: {curr['explanation']}")
                if st.button("Tiếp theo ⏭️"):
                    st.session_state.current_q += 1; st.session_state.show_explanation = False; st.rerun()
        
        # Bước 3: Hoàn thành bài thi
        else:
            st.balloons()
            st.header("🏆 Hoàn thành bài thi!")
            st.subheader(f"{st.session_state.student_name} ({st.session_state.student_class}) - Điểm: {st.session_state.score}/{total}")
            
            # Tự động lưu 1 lần
            if "saved_final" not in st.session_state:
                save_result(st.session_state.active_quiz_id, st.session_state.student_name, st.session_state.student_class, st.session_state.score, st.session_state.wrong_answers)
                st.session_state.saved_final = True
            
            # Góc Ôn Tập
            st.divider()
            st.subheader("📚 Góc Ôn Tập: Các câu trả lời sai")
            if st.session_state.wrong_answers:
                for w in st.session_state.wrong_answers:
                    with st.expander(f"Câu {w['q_num']}: {w['question']}"):
                        st.error(f"❌ Bạn đã chọn: {w['wrong_choice']}")
                        st.success(f"✅ Đáp án đúng: {w['correct_answer']}")
                        st.info(f"💡 Giải thích: {w['explanation']}")
            else:
                st.success("Tuyệt đỉnh! Bạn không làm sai câu nào cả! 🎉")
                
            if st.button("Thoát Về Trang Chủ"):
                for key in ['active_quiz_id', 'student_name', 'student_class', 'quiz_data', 'current_q', 'score', 'show_explanation', 'wrong_answers', 'saved_final']:
                    if key in st.session_state: del st.session_state[key]
                st.rerun()