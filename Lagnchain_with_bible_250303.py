#streamlit run Lagnchain_with_bible_250303.py
#실행 streamlit run Lagnchain_with_bible_250303.py --server.address=0.0.0.0 --server.port=8501
import streamlit as st

from langchain.schema.runnable import RunnableMap
from langchain.retrievers.multi_query import MultiQueryRetriever

import google.generativeai as genai
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import FAISS
import os
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.document_loaders import TextLoader

import re

from langchain_google_genai import ChatGoogleGenerativeAI

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever  #TF-IDF 계열의 검색 알고리즘
from langchain.retrievers import EnsembleRetriever # 여러 retriever를 입력으로 받아 처리
from langchain_community.vectorstores.faiss import DistanceStrategy #vectorstores의 거리 계산
from langchain.memory import ConversationBufferWindowMemory

import pickle
import time

def get_conversation_chain(vectorstore,data_list,query,st_memory):
   
    #llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-thinking-exp", temperature=0)
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0)

    template = """당신은 인공지능 ChatBOT으로 Question 내용에 대해서 대답합니다.
    대답은 Context에 있는 내용을 참조해서만 답변합니다.
    되도록이면 자세한 내용으로 대답하고 context의 있는 original source도 같이 보여주세요.
    #Chat history: 
    {chat_history}
    #Context: 
    {context}
    #Question:
    {question}

    #Answer:
    """

    prompt = ChatPromptTemplate.from_template(template)

    faiss_retriever=vectorstore.as_retriever(search_type="mmr",
    search_kwargs={'k':10, 'fetch_k': 30})

    # initialize the bm25 retriever(10개)
    bm25_retriever = BM25Retriever.from_documents(data_list)
    bm25_retriever.k = 10

    f_ratio = 0.7
    # initialize the ensemble retriever
    #retriever 가중치 설정(bm25:30% + faiss:70%)
    # 문서 결합 방식 설정(default setting:combine_documents-결합된 문서들을 합치는 방식으로 동작)
    ensemble_retriever_combine = EnsembleRetriever(
        retrievers=[bm25_retriever, faiss_retriever], weights=[1-f_ratio, f_ratio] 
        ,retriever_type="combine_documents")
    
    multiqueryretriever = MultiQueryRetriever.from_llm(ensemble_retriever_combine, llm=llm)


    memory = st_memory

    chain = (
      RunnableMap({
        "context": lambda x: multiqueryretriever.invoke(x['question']),
        "question": lambda x: x['question'],
        'chat_history' : lambda x: x['chat_history']
    }) | prompt | llm | StrOutputParser())


    #실시간 출력(Stream)
    response = ''
    sentence = ''

    response = chain.invoke({'question': query,'chat_history': memory.chat_memory.messages})

    if '\n' not in response:
        st.write(response)

    else: 
        for chunk in response:
            #st.write(chunk)
            if chunk in ['\n','\n\n', '\n\n\n']:
                st.write(sentence)
                time.sleep(0.1)
                sentence = ''
            else:
                sentence = sentence + chunk
    
    memory.save_context({"input": query}, {"output": response})

    return response

def handle_userinput(user_question):
    response = st.session_state.conversation({'question': user_question})
    st.session_state.chat_history = response['chat_history']

    for i, message in enumerate(st.session_state.chat_history):
        if i % 2 == 0:
            st.write(f"Human: {message.content}")
        else:
            st.write(f"AI: {message.content}")

# 대화 히스토리를 문자열로 변환하는 함수
def get_chat_history_str(chat_history):
    return "\n".join([f"{entry['role'].capitalize()}: {entry['content']}" for entry in chat_history])

def file_read():
    folder_path = "C:\\python\\Bible-Rag\\new_data"
    file_list = os.listdir(folder_path)

    documents = []
    pattern2 = r'[가-힣]+'

    for file_name in file_list:
        loader = TextLoader(folder_path+'\\'+file_name, encoding='utf-8')
        document = loader.load()
        result2 = re.search(pattern2, file_name)
        if result2:
            book_name = result2.group()
        document[0].metadata = {'source':book_name}
        documents.append(document)

    document_list = []
    for index,i in enumerate(documents):
        document_list.append(i[0])

    return document_list

def text_splitter(document_list):
    # 2000자(overlap=50로 청킹하기
    text_splitter = RecursiveCharacterTextSplitter(chunk_size = 3000,chunk_overlap = 50)
    #splitter를 이용한 문서 청킹
    data = text_splitter.split_documents(document_list)

    return data

def make_vectorstore(data):

    #임베딩 모델
    embeddings = HuggingFaceEmbeddings(model_name='jhgan/ko-sroberta-multitask')

    vectorstore = FAISS.from_documents(documents=data, embedding=embeddings)

    st.success(f"총 {len(data)}개의 페이지를 성공적으로 로드했습니다.")
    
    return vectorstore

def load_bible(vector_distance_cal):
    with st.spinner("파일 불러오는 중..."):
        
        #임베딩 모델 불로오기
        embeddings = HuggingFaceEmbeddings(model_name='jhgan/ko-sroberta-multitask')
        
        # 저장된 인덱스 로드(allow_dangerous_deserialization=True 필요)
        vectorstore = FAISS.load_local("Rag_data/bible_embed", 
        embeddings,
        distance_strategy=vector_distance_cal, 
        allow_dangerous_deserialization=True)

        with open("Rag_data/bible_data.pkl", 'rb') as f:
            data_load = pickle.load(f)
    
    st.success(f"총 {len(data_load)}개의 페이지를 성공적으로 로드했습니다.")

    return data_load, vectorstore

def main():

    st.set_page_config(page_title="Lagnchain_with_bible", page_icon=":books:")
    st.title("🦜🔗 Lagnchain_with_bible")

    if "conversation" not in st.session_state:
        st.session_state.conversation = None
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "vectorstore" not in st.session_state:
        st.session_state.vectorstore = None
    if "document_list" not in st.session_state:
        st.session_state.document_list = []
    if "vector_option" not in st.session_state:
        st.session_state.vector_option = None

    #윈도우 크기 k를 지정하면 최근 k개의 대화만 기억하고 이전 대화는 삭제
    if "memory" not in st.session_state:
        st.session_state.memory = ConversationBufferWindowMemory(memory_key="chat_history", k=4) 

    with st.sidebar:
        gemini_api_key = st.text_input('Gemini_API_KEY를 입력하세요.', key="langchain_search_api_gemini", type="password")
        "[Get an Gemini API key](https://ai.google.dev/)"
        "[How to get Gemini API Key](https://luvris2.tistory.com/880)"

        if (gemini_api_key[0:2] != 'AI') or (len(gemini_api_key) != 39):
            st.warning('잘못된 key 입력', icon='⚠️')
        else:
            st.success('정상 key 입력', icon='👉')

        if process :=st.button("Process"):
            if (gemini_api_key[0:2] != 'AI') or (len(gemini_api_key) != 39):
                st.error("잘못된 key 입력입니다. 다시 입력해 주세요.")
                st.stop()

        if data_clear :=st.button("대화 클리어"):
            st.session_state.conversation = None
            st.session_state.chat_history = []
            st.session_state.memory = ConversationBufferWindowMemory(memory_key="chat_history", k=4)

        vector_option = ["EUCLIDEAN_DISTANCE","MAX_INNER_PRODUCT", "DOT_PRODUCT"]

        if vector_option_1 := st.selectbox("Select the vector distance cal method?",
                                           options=vector_option,
                                           index=0):

            st.info(f"You selected: {vector_option_1}")

            if vector_option_1 == "EUCLIDEAN_DISTANCE":
                #유클리드 거리(L2)
                st.session_state.vector_option = DistanceStrategy.EUCLIDEAN_DISTANCE 
                
            if vector_option_1 == "MAX_INNER_PRODUCT":
                #내적(코사인 유사도와 유사)
                st.session_state.vector_option = DistanceStrategy.MAX_INNER_PRODUCT

            if vector_option_1 == "DOT_PRODUCT":
                #점곱(내적과 동일)
                st.session_state.vector_option = DistanceStrategy.DOT_PRODUCT  
            

    #0. gemini api key Setting
    if not gemini_api_key:
        st.warning("Gemini API Key를 입력해 주세요.")
        st.stop()

    genai.configure(api_key=gemini_api_key)

    #0. gemini api key Setting
    os.environ["GOOGLE_API_KEY"] = gemini_api_key

    # 파일이 업로드되면 처리
    if st.session_state.vectorstore == None:

        st.session_state.document_list, st.session_state.vectorstore = load_bible(st.session_state.vector_option)

    st.chat_message("assistant").write("안녕하세요. 무엇을 도와드릴까요?")

    #2. 이전 대화 내용을 출력
    # st.session_state['chat_history']가 있으면 실행
    if ("chat_history" in st.session_state) and (len(st.session_state['chat_history'])>0):
        #st.session_state['messages']는 tuple 형태로 저장되어 있음.
        for role, message in st.session_state['chat_history']: 
            st.chat_message(role).write(message)

    #3. query를 입력받는다.
    if query := st.chat_input("질문을 입력해주세요."):

        #4.'user' icon으로 query를 출력한다.
        st.chat_message("user").write(query)
        #5. query를 session_state 'user'에 append 한다.
        st.session_state['chat_history'].append(('user',query))

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):

                start_time = time.time()

                # chain 호출
                response = get_conversation_chain(
                    st.session_state.vectorstore,
                    st.session_state.document_list,
                    query,
                    st.session_state.memory)
                
                #st.write(st.session_state.memory.chat_memory.messages)
                
                end_time = time.time()
                total_time = (end_time - start_time)
                st.info(f"검색 소요 시간: {total_time}초")

                #st.write(response)
                #6. response session_state 'assistant'에 append 한다.
                st.session_state['chat_history'].append(('assistant',response))

if __name__ == '__main__':
    main()