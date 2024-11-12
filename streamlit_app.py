# streamlit_app.py

import streamlit as st
from streamlit_tags import st_tags_sidebar
import pandas as pd
import json
from datetime import datetime
from scraper import (
    fetch_html_selenium,
    save_raw_data,
    format_data,
    save_formatted_data,
    calculate_price,
    html_to_markdown_with_readability,
    create_dynamic_listing_model,
    create_listings_container_model,
    scrape_url,
    setup_selenium,
    generate_unique_folder_name
)
from pagination_detector import detect_pagination_elements
import re
from urllib.parse import urlparse
from assets import PRICING
import os

# Initialize Streamlit app
st.set_page_config(page_title="Raspador de Dados de Farmácias", page_icon="💊")
st.title("Raspador de Dados de Farmácias 💊")

# Initialize session state variables
if 'scraping_state' not in st.session_state:
    st.session_state['scraping_state'] = 'idle'  # Possible states: 'idle', 'waiting', 'scraping', 'completed'
if 'results' not in st.session_state:
    st.session_state['results'] = None
if 'driver' not in st.session_state:
    st.session_state['driver'] = None

# Sidebar components
st.sidebar.title("Configurações")

# API Keys
with st.sidebar.expander("API Keys", expanded=False):
    # st.session_state['openai_api_key'] = st.text_input("OpenAI API Key", type="password")
    # st.session_state['gemini_api_key'] = st.text_input("Gemini API Key", type="password")
    st.session_state['groq_api_key'] = st.text_input("Groq API Key", type="password")

# Model selection
model_selection = st.sidebar.selectbox("Selecione o Modelo", options=list(PRICING.keys()), index=0)

# URL input
url_input = st.sidebar.text_input("URL(s) separados dos espaços")
# Process URLs
urls = url_input.strip().split()
num_urls = len(urls)
# Fields to extract
show_tags = st.sidebar.toggle("Raspar")
fields = []
if show_tags:
    fields = st_tags_sidebar(
        label='Dados a raspar',
        text='Enter para adicionar um dado',
        value=[
            "Nome",
            "Preço",
            "Marca",
            "Informação Adicional"
        ],
        suggestions=[],
        maxtags=-1,
        key='fields_input'
    )

st.sidebar.markdown("---")

# Conditionally display Pagination and Attended Mode options
if num_urls <= 1:
    # Pagination settings
    use_pagination = st.sidebar.toggle("Paginação")
    pagination_details = ""
    if use_pagination:
        pagination_details = st.sidebar.text_input(
            "Digite Detalhes de Paginação (opcional)",
            help="Descreva como navegar pelas páginas (ex.: classe do botão 'Próximo', padrão da URL)"
        )

    st.sidebar.markdown("---")

    # Attended mode toggle
    attended_mode = st.sidebar.toggle("Modo Guiado")
else:
    # Multiple URLs entered; disable Pagination and Attended Mode
    use_pagination = False
    attended_mode = False
    # Inform the user
    st.sidebar.info("Paginação e Modo guiado são desativados com múltiplas urls.")

st.sidebar.markdown("---")



# Main action button
if st.sidebar.button("LAUNCH SCRAPER", type="primary"):
    if url_input.strip() == "":
        st.error("Coloque ao menos uma URL")
    elif show_tags and len(fields) == 0:
        st.error("Por favor, insira pelo menos um campo para extrair.")
    else:
        # Set up scraping parameters in session state
        st.session_state['urls'] = url_input.strip().split()
        st.session_state['fields'] = fields
        st.session_state['model_selection'] = model_selection
        st.session_state['attended_mode'] = attended_mode
        st.session_state['use_pagination'] = use_pagination
        st.session_state['pagination_details'] = pagination_details
        st.session_state['scraping_state'] = 'waiting' if attended_mode else 'scraping'

# Scraping logic
if st.session_state['scraping_state'] == 'waiting':
    # Attended mode: set up driver and wait for user interaction
    if st.session_state['driver'] is None:
        st.session_state['driver'] = setup_selenium(attended_mode=True)
        st.session_state['driver'].get(st.session_state['urls'][0])
        st.write("Realize quaisquer ações necessárias na janela do navegador que foi aberta.")
        st.write("Navegue até a página que deseja raspar.")
        st.write("Quando estiver pronto, clique no botão 'Retomar Raspagem'.")
    else:
        st.write("A janela do navegador já está aberta. Realize suas ações e clique em 'Retomar Raspagem'.")

    if st.button("Retomar Raspagem"):
        st.session_state['scraping_state'] = 'scraping'
        st.rerun()

elif st.session_state['scraping_state'] == 'scraping':
    with st.spinner('Raspando...'):
        # Perform scraping
        output_folder = os.path.join('output', generate_unique_folder_name(st.session_state['urls'][0]))
        os.makedirs(output_folder, exist_ok=True)

        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0
        all_data = []
        pagination_info = None

        driver = st.session_state.get('driver', None)
        if st.session_state['attended_mode'] and driver is not None:
            # Attended mode: scrape the current page without navigating
            # Fetch HTML from the current page
            raw_html = fetch_html_selenium(st.session_state['urls'][0], attended_mode=True, driver=driver)
            markdown = html_to_markdown_with_readability(raw_html)
            save_raw_data(markdown, output_folder, f'rawData_1.md')

            current_url = driver.current_url  # Use the current URL for logging and saving purposes

            # Detect pagination if enabled
            if st.session_state['use_pagination']:
                pagination_data, token_counts, pagination_price = detect_pagination_elements(
                    current_url, st.session_state['pagination_details'], st.session_state['model_selection'], markdown
                )
                # Check if pagination_data is a dict or a model with 'page_urls' attribute
                if isinstance(pagination_data, dict):
                    page_urls = pagination_data.get("page_urls", [])
                else:
                    page_urls = pagination_data.page_urls
                
                pagination_info = {
                    "page_urls": page_urls,
                    "token_counts": token_counts,
                    "price": pagination_price
                }
            # Scrape data if fields are specified
            if show_tags:
                # Create dynamic models
                DynamicListingModel = create_dynamic_listing_model(st.session_state['fields'])
                DynamicListingsContainer = create_listings_container_model(DynamicListingModel)
                # Format data
                formatted_data, token_counts = format_data(
                    markdown, DynamicListingsContainer, DynamicListingModel, st.session_state['model_selection']
                )
                input_tokens, output_tokens, cost = calculate_price(token_counts, st.session_state['model_selection'])
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_cost += cost
                # Save formatted data
                df = save_formatted_data(formatted_data, output_folder, f'sorted_data_1.json', f'sorted_data_1.xlsx')
                all_data.append(formatted_data)
        else:
            # Non-attended mode or driver not available
            for i, url in enumerate(st.session_state['urls'], start=1):
                # Fetch HTML
                raw_html = fetch_html_selenium(url, attended_mode=False)
                markdown = html_to_markdown_with_readability(raw_html)
                save_raw_data(markdown, output_folder, f'rawData_{i}.md')

                # Detect pagination if enabled and only for the first URL
                if st.session_state['use_pagination'] and i == 1:
                    pagination_data, token_counts, pagination_price = detect_pagination_elements(
                        url, st.session_state['pagination_details'], st.session_state['model_selection'], markdown
                    )
                    # Check if pagination_data is a dict or a model with 'page_urls' attribute
                    if isinstance(pagination_data, dict):
                        page_urls = pagination_data.get("page_urls", [])
                    else:
                        page_urls = pagination_data.page_urls
                    
                    pagination_info = {
                        "page_urls": page_urls,
                        "token_counts": token_counts,
                        "price": pagination_price
                    }
                # Scrape data if fields are specified
                if show_tags:
                    # Create dynamic models
                    DynamicListingModel = create_dynamic_listing_model(st.session_state['fields'])
                    DynamicListingsContainer = create_listings_container_model(DynamicListingModel)
                    # Format data
                    formatted_data, token_counts = format_data(
                        markdown, DynamicListingsContainer, DynamicListingModel, st.session_state['model_selection']
                    )
                    input_tokens, output_tokens, cost = calculate_price(token_counts, st.session_state['model_selection'])
                    total_input_tokens += input_tokens
                    total_output_tokens += output_tokens
                    total_cost += cost
                    # Save formatted data
                    df = save_formatted_data(formatted_data, output_folder, f'sorted_data_{i}.json', f'sorted_data_{i}.xlsx')
                    all_data.append(formatted_data)

        # Clean up driver if used
        if driver:
            driver.quit()
            st.session_state['driver'] = None

        # Save results
        st.session_state['results'] = {
            'data': all_data,
            'input_tokens': total_input_tokens,
            'output_tokens': total_output_tokens,
            'total_cost': total_cost,
            'output_folder': output_folder,
            'pagination_info': pagination_info
        }
        st.session_state['scraping_state'] = 'completed'
# Display results
if st.session_state['scraping_state'] == 'completed' and st.session_state['results']:
    results = st.session_state['results']
    all_data = results['data']
    total_input_tokens = results['input_tokens']
    total_output_tokens = results['output_tokens']
    total_cost = results['total_cost']
    output_folder = results['output_folder']
    pagination_info = results['pagination_info']

    # Display scraping details
    if show_tags:
        st.subheader("Scraping Results")
        for i, data in enumerate(all_data, start=1):
            st.write(f"Data from URL {i}:")
            
            # Handle string data (convert to dict if it's JSON)
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    st.error(f"Falha ao interpretar os dados como JSON para a URL {i}")
                    continue
            
            if isinstance(data, dict):
                if 'listings' in data and isinstance(data['listings'], list):
                    df = pd.DataFrame(data['listings'])
                else:
                    # If 'listings' is not in the dict or not a list, use the entire dict
                    df = pd.DataFrame([data])
            elif hasattr(data, 'listings') and isinstance(data.listings, list):
                # Handle the case where data is a Pydantic model
                listings = [item.dict() for item in data.listings]
                df = pd.DataFrame(listings)
            else:
                st.error(f"Formato de dados inesperado para a URL {i}")
                continue
            # Display the dataframe
            st.dataframe(df, use_container_width=True)

        # Display token usage and cost
        st.sidebar.markdown("---")
        st.sidebar.markdown("### Detalhes")
        st.sidebar.markdown("#### Uso de Tokens")
        st.sidebar.markdown(f"*Input Tokens:* {total_input_tokens}")
        st.sidebar.markdown(f"*Output Tokens:* {total_output_tokens}")
        st.sidebar.markdown(f"**Total Cost:** :green-background[**${total_cost:.4f}**]")

        # Download options
        st.subheader("Baixar dados extraídos")
        col1, col2 = st.columns(2)
        with col1:
            json_data = json.dumps(all_data, default=lambda o: o.dict() if hasattr(o, 'dict') else str(o), indent=4)
            st.download_button(
                "JSON",
                data=json_data,
                file_name="scraped_data.json"
            )
        with col2:
            # Convert all data to a single DataFrame
            all_listings = []
            for data in all_data:
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                if isinstance(data, dict) and 'listings' in data:
                    all_listings.extend(data['listings'])
                elif hasattr(data, 'listings'):
                    all_listings.extend([item.dict() for item in data.listings])
                else:
                    all_listings.append(data)
            
            combined_df = pd.DataFrame(all_listings)
            st.download_button(
                "CSV",
                data=combined_df.to_csv(index=False),
                file_name="scraped_data.csv"
            )

        st.success(f"Resultados Salvos em: {output_folder}")

    # Display pagination info
    if pagination_info:
        st.markdown("---")
        st.subheader("Informação da Paginação")

        # Display token usage and cost using metrics
        st.sidebar.markdown("---")
        st.sidebar.markdown("### Pagination Details")
        st.sidebar.markdown(f"**Number of Page URLs:** {len(pagination_info['page_urls'])}")
        st.sidebar.markdown("#### Pagination Token Usage")
        st.sidebar.markdown(f"*Input Tokens:* {pagination_info['token_counts']['input_tokens']}")
        st.sidebar.markdown(f"*Output Tokens:* {pagination_info['token_counts']['output_tokens']}")
        st.sidebar.markdown(f"**Pagination Cost:** :blue-background[**${pagination_info['price']:.4f}**]")


        # Display page URLs in a table
        st.write("**URLs:**")
        # Make URLs clickable
        pagination_df = pd.DataFrame(pagination_info["page_urls"], columns=["Page URLs"])
        
        st.dataframe(
            pagination_df,
            column_config={
                "Page URLs": st.column_config.LinkColumn("Page URLs")
            },use_container_width=True
        )

        # Download pagination URLs
        st.subheader("Baixar URLs de paginação")
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("CSV",data=pagination_df.to_csv(index=False),file_name="pagination_urls.csv")
        with col2:
            st.download_button("JSON",data=json.dumps(pagination_info['page_urls'], indent=4),file_name="pagination_urls.json")
    # Reset scraping state
    if st.sidebar.button("Clear Results"):
        st.session_state['scraping_state'] = 'idle'
        st.session_state['results'] = None

   # If both scraping and pagination were performed, show totals under the pagination table
    if show_tags and pagination_info:
        st.markdown("---")
        total_input_tokens_combined = total_input_tokens + pagination_info['token_counts']['input_tokens']
        total_output_tokens_combined = total_output_tokens + pagination_info['token_counts']['output_tokens']
        total_combined_cost = total_cost + pagination_info['price']
        # st.markdown("### Total Counts and Cost (Including Pagination)")
        # st.markdown(f"**Total Input Tokens:** {total_input_tokens_combined}")
        # st.markdown(f"**Total Output Tokens:** {total_output_tokens_combined}")
        # st.markdown(f"**Total Combined Cost:** :rainbow-background[**${total_combined_cost:.4f}**]")
# Helper function to generate unique folder names
def generate_unique_folder_name(url):
    timestamp = datetime.now().strftime('%Y_%m_%d__%H_%M_%S')
    
    # Parse the URL
    parsed_url = urlparse(url)
    
    # Extract the domain name
    domain = parsed_url.netloc or parsed_url.path.split('/')[0]
    
    # Remove 'www.' if present
    domain = re.sub(r'^www\.', '', domain)
    
    # Remove any non-alphanumeric characters and replace with underscores
    clean_domain = re.sub(r'\W+', '_', domain)
    
    return f"{clean_domain}_{timestamp}"
