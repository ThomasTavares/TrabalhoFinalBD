import mysql.connector
import openai
import requests
import json
import re
import random
import time
import io 
from PIL import Image, ImageDraw, ImageFont

from db_operations import insert_data_from_json, get_schema_info


def get_openai_key():
    """Obtém a chave de API da OpenAI do arquivo de configuração."""
    api_key_file = "/home/samuks369/Downloads/gpt-key.txt"
    # api_key_file = "C:\\Users\\thoma\\Documents\\GitHub\\openai_key.txt"
    
    try:
        with open(api_key_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Arquivo de chave não encontrado: {api_key_file}")
        return None
    except IOError as e:
        print(f"Erro ao ler chave API: {e}")
        return None


api_key = get_openai_key()
if api_key:
    openai.api_key = api_key
else:
    print("Chave OpenAI não configurada - funcionalidades de IA podem não funcionar")


def check_ai_dependencies():
    """Verifica disponibilidade das dependências de IA."""
    dependencies = {
        'openai': 'OpenAI API',
        'PIL': 'Pillow para imagens', 
        'torch': 'PyTorch',
        'transformers': 'Transformers',
        'sklearn': 'Scikit-learn'
    }
    
    missing = []
    for dep in dependencies:
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)
    
    if missing:
        print(f"\n⚠️  Dependências ausentes: {', '.join(missing)}")
        print("Algumas funcionalidades podem não funcionar.")
        return False
    
    print("✅ Todas as dependências de IA disponíveis")
    return True


def generate_data(prompt, modelo="gpt-4o-mini", temperatura=0.4):
    """Gera dados usando a API da OpenAI."""
    if not openai.api_key:
        print("Chave OpenAI não configurada")
        return None
    
    try:
        response = openai.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperatura,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Erro na API OpenAI: {e}")
        return None


def build_prompt(schema: dict, tabela_alvo: str, n_linhas: int, contexto_dados: dict = None, foreign_keys_data: dict = None):
    """Constrói prompt otimizado para geração de dados válidos."""
    
    # Constraints essenciais por tabela
    constraints = {
        'taxon': {'Tipo': ['Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero']},
        'especie': {'IUCN': ['LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX']},
        'projeto': {'Status': ['Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']},
        'contrato': {'Status': ['Pendente', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']}
    }
    
    # Schema da tabela atual
    campos_info = []
    if tabela_alvo in schema:
        for col in schema[tabela_alvo]:
            campo_tipo = f"{col['nome']}: {col['tipo']}"
            if 'blob' in col['tipo'].lower():
                campo_tipo += " (sempre null no JSON)"
            campos_info.append(campo_tipo)
    
    # Contexto de FKs disponíveis
    fk_context = ""
    if foreign_keys_data:
        fk_context = "\nCHAVES ESTRANGEIRAS VÁLIDAS:\n"
        for campo, valores in foreign_keys_data.items():
            ids_validos = [str(v[0]) for v in valores[:10]]  # Primeiros 10 IDs
            fk_context += f"- {campo}: [{', '.join(ids_validos)}]\n"
    
    # Constraints específicas
    constraint_info = ""
    tabela_lower = tabela_alvo.lower()
    if tabela_lower in constraints:
        constraint_info = f"\nCONSTRAINTS OBRIGATÓRIAS:\n"
        for campo, valores in constraints[tabela_lower].items():
            constraint_info += f"- {campo}: APENAS {valores}\n"
    
    prompt = f"""
Sistema de taxonomia científica. Gere {n_linhas} registros para `{tabela_alvo}`.

SCHEMA:
{chr(10).join(campos_info)}

{fk_context}
{constraint_info}

REGRAS:
1. Use APENAS valores de FKs listados acima
2. Use APENAS valores de constraints listados
3. CPF: 11 dígitos numéricos
4. DOI: formato "10.xxxx/yyyy"
5. Datas: formato "YYYY-MM-DD"
6. BLOB: sempre null
7. Nomes científicos reais e válidos

FORMATO OBRIGATÓRIO:
{{
    "registros": [
        {{"campo1": valor1, "campo2": "valor2"}}
    ]
}}

RESPONDA APENAS COM O JSON.
"""
    
    return prompt.strip()


def build_prompt_for_media_table(schema: dict, tabela_alvo: str, n_linhas=20):
    """Gera prompt específico para a tabela Midia."""
    if tabela_alvo.lower() != 'midia':
        return build_prompt(schema, tabela_alvo, n_linhas, {}, {})
    
    prompt = f"""
Gere {n_linhas} registros JSON para a tabela Midia (mídia científica):

Campos:
- ID_Midia: integer (sequencial)
- ID_Especime: integer (valores 1-{min(10, n_linhas)})
- Tipo: varchar(50) (tipos: "Fotografia dorsal", "Microscopia 40x", "Áudio vocalização", "Video comportamental")
- Dado: blob (SEMPRE null - imagens inseridas separadamente)

FORMATO:
{{
    "registros": [
        {{"ID_Midia": 1, "ID_Especime": 1, "Tipo": "Fotografia lateral", "Dado": null}}
    ]
}}

RESPONDA APENAS COM O JSON.
"""
    return prompt.strip()


def validate_generated_data(registros, tabela_nome, schema):
    """Valida e corrige dados gerados pela IA."""
    if not registros or not isinstance(registros, list):
        return []
    
    # Constraints por tabela
    constraints = {
        'taxon': {'Tipo': ['Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero']},
        'especie': {'IUCN': ['LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX']},
        'projeto': {'Status': ['Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']},
        'contrato': {'Status': ['Pendente', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']}
    }
    
    registros_validos = []
    tabela_constraints = constraints.get(tabela_nome.lower(), {})
    
    for i, registro in enumerate(registros):
        if not isinstance(registro, dict):
            continue
        
        registro_corrigido = {}
        
        for campo, valor in registro.items():
            # Valida constraints específicas
            if campo in tabela_constraints:
                valores_validos = tabela_constraints[campo]
                if valor not in valores_validos:
                    valor = valores_validos[0]  # Usa o primeiro valor como padrão
                    print(f"  Corrigindo {campo}: valor inválido → {valor}")
            
            # Valida CPF
            elif campo == 'CPF' and valor:
                cpf_limpo = re.sub(r'\D', '', str(valor))
                if len(cpf_limpo) != 11:
                    cpf_limpo = ''.join([str(random.randint(0, 9)) for _ in range(11)])
                    print(f"  Corrigindo CPF inválido → {cpf_limpo}")
                valor = cpf_limpo
            
            # Valida DOI
            elif campo == 'DOI' and valor:
                if not re.match(r'^10\.\d+/.+', str(valor)):
                    valor = f"10.{random.randint(1000, 9999)}/exemplo.{random.randint(2020, 2024)}"
                    print(f"  Corrigindo DOI → {valor}")
            
            # Valida datas
            elif ('data' in campo.lower() or 'dt_' in campo.lower()) and valor:
                if not re.match(r'^\d{4}-\d{2}-\d{2}', str(valor)):
                    valor = f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
                    print(f"  Corrigindo data em {campo} → {valor}")
            
            # Valida valores monetários
            elif campo == 'Valor' and valor:
                try:
                    valor_float = float(valor)
                    if valor_float <= 0:
                        valor = round(random.uniform(3000.0, 25000.0), 2)
                    else:
                        valor = round(valor_float, 2)
                except (ValueError, TypeError):
                    valor = round(random.uniform(3000.0, 25000.0), 2)
            
            registro_corrigido[campo] = valor
        
        if registro_corrigido:
            registros_validos.append(registro_corrigido)
    
    print(f"  Validação: {len(registros_validos)}/{len(registros)} registros válidos")
    return registros_validos


def clean_json_response(response):
    """Limpa a resposta da IA removendo markdown e texto extra."""
    if not response:
        return response
    
    # Remove blocos markdown
    response = re.sub(r'```json\s*', '', response, flags=re.IGNORECASE)
    response = re.sub(r'```\s*', '', response)
    
    # Encontra JSON válido entre { }
    start = response.find('{')
    end = response.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        return response[start:end + 1]
    
    return response.strip()


def search_image_web(nome_especie, timeout=10):
    """Busca imagem na web usando Lorem Picsum com seed baseada no nome."""
    try:
        seed = abs(hash(nome_especie)) % 1000
        url = f"https://picsum.photos/400/300?random={seed}"
        
        response = requests.get(url, timeout=timeout)
        if response.status_code == 200 and len(response.content) > 1000:
            return response.content
    except (requests.RequestException, ValueError, IOError) as e:
        print(f"Erro ao buscar imagem para '{nome_especie}': {e}")
    
    return None


def search_image_web_improved(nome_especie, timeout=10):
    """Versão melhorada com múltiplas tentativas de URLs."""
    try:
        # URLs com diferentes seeds baseados no nome
        urls = [
            f"https://picsum.photos/400/300?random={abs(hash(nome_especie)) % 1000}",
            f"https://picsum.photos/450/350?random={abs(hash(nome_especie + 'bio')) % 1000}",
        ]
        
        for i, url in enumerate(urls):
            try:
                print(f"      Tentativa {i+1}: buscando imagem...")
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200 and len(response.content) > 1000:
                    print(f"Imagem obtida ({len(response.content)} bytes)")
                    return response.content
            except (requests.RequestException, ValueError) as e:
                print(f"Erro na tentativa {i+1}: {e}")
                continue
                
    except Exception as e:
        print(f"Erro geral ao buscar imagem para '{nome_especie}': {e}")
    
    return None


def create_placeholder_image_improved(nome_especie, nome_popular=None, descricao=None, tamanho=(400, 300)):
    """Versão melhorada de placeholder com mais informações."""
    try:
        # Cor baseada no tipo de organismo
        cor_base = abs(hash(nome_especie)) % 0xFFFFFF
        
        if descricao:
            desc_lower = descricao.lower()
            if any(palavra in desc_lower for palavra in ['plant', 'planta', 'vegetal']):
                cor_base = 0x4CAF50  # Verde
            elif any(palavra in desc_lower for palavra in ['animal', 'fauna']):
                cor_base = 0xFF9800  # Laranja
            elif any(palavra in desc_lower for palavra in ['fungi', 'fungo']):
                cor_base = 0x8BC34A  # Verde claro
            elif any(palavra in desc_lower for palavra in ['bacteria', 'microb']):
                cor_base = 0x2196F3  # Azul
        
        cor_rgb = ((cor_base >> 16) & 255, (cor_base >> 8) & 255, cor_base & 255)
        cor_rgb = tuple(min(255, max(50, c + 80)) for c in cor_rgb)
        
        img = Image.new('RGB', tamanho, color=cor_rgb)
        draw = ImageDraw.Draw(img)
        
        # Borda
        border_color = tuple(max(0, c - 40) for c in cor_rgb)
        draw.rectangle([0, 0, tamanho[0]-1, tamanho[1]-1], outline=border_color, width=3)
        
        # Fontes
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
            font_subtitle = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except OSError:
            font_title = ImageFont.load_default()
            font_subtitle = ImageFont.load_default()
        
        # Textos
        textos = [nome_especie]
        if nome_popular and nome_popular.strip():
            textos.append(f"({nome_popular})")
        
        y_offset = tamanho[1] // 2 - 30
        
        for i, texto in enumerate(textos):
            font = font_title if i == 0 else font_subtitle
            
            bbox = draw.textbbox((0, 0), texto, font=font)
            text_width = bbox[2] - bbox[0]
            x = (tamanho[0] - text_width) // 2
            
            # Sombra e texto
            draw.text((x + 1, y_offset + 1), texto, fill='black', font=font)
            draw.text((x, y_offset), texto, fill='white', font=font)
            
            y_offset += 25
        
        # Converte para bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()
        
    except Exception as e:
        print(f"Erro ao criar placeholder melhorado para '{nome_especie}': {e}")
        return create_placeholder_image(nome_especie, tamanho)


def create_placeholder_image(nome_especie, tamanho=(400, 300)):
    """Cria imagem placeholder simples com o nome da espécie."""
    try:
        # Cor baseada no hash do nome
        cor_base = abs(hash(nome_especie)) % 0xFFFFFF
        cor_rgb = ((cor_base >> 16) & 255, (cor_base >> 8) & 255, cor_base & 255)
        cor_rgb = tuple(min(255, max(50, c + 100)) for c in cor_rgb)
        
        img = Image.new('RGB', tamanho, color=cor_rgb)
        draw = ImageDraw.Draw(img)
        
        # Fonte
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except OSError:
            font = ImageFont.load_default()
        
        # Texto centralizado
        bbox = draw.textbbox((0, 0), nome_especie, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (tamanho[0] - text_width) // 2
        y = (tamanho[1] - text_height) // 2
        
        draw.text((x, y), nome_especie, fill='white', font=font)
        
        # Converte para bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()
        
    except Exception as e:
        print(f"Erro ao criar placeholder para '{nome_especie}': {e}")
        return None


def populate_all_tables(conexao, n_linhas=10, n_especies=20):
    """
    Versão otimizada que popula todas as tabelas garantindo integridade referencial
    e coerência semântica entre os dados gerados.
    """
    # VERIFICA SE AS TABELAS EXISTEM ANTES DE TENTAR POPULAR
    cursor = conexao.cursor()
    cursor.execute("SHOW TABLES")
    tabelas_banco = cursor.fetchall()
    cursor.close()
    
    if not tabelas_banco:
        print("\nERRO: Nenhuma tabela encontrada no banco de dados!")
        print("\nSOLUÇÃO: Você precisa criar as tabelas primeiro.")
        return
    
    # Cria mapeamento de nomes case-insensitive para nomes reais
    tabelas_existentes = {}
    for (nome_real,) in tabelas_banco:
        tabelas_existentes[nome_real.lower()] = nome_real
    
    print(f"\nTabelas encontradas no banco: {list(tabelas_existentes.values())}")
    
    schema = get_schema_info(conexao)
    
    # ORDEM OTIMIZADA respeitando dependências de chave estrangeira
    ordem = [
        # Tabelas base (sem dependências)
        "taxon",           # Base da taxonomia
        "local_de_coleta", # Independente
        "funcionario",     # Independente
        "categoria",       # Independente  
        "laboratorio",     # Independente
        "financiador",     # Independente
        "projeto",         # Independente (movido antes)
        
        # Tabelas com uma dependência
        "hierarquia",      # Depende de taxon
        "especie",         # Depende de taxon (gênero)
        "equipamento",     # Depende de laboratorio
        
        # Tabelas com duas dependências
        "especime",        # Depende de especie
        "amostra",         # Depende de especie e local_de_coleta
        "artigo",          # Depende de projeto
        "contrato",        # Depende de funcionario e laboratorio
        "financiamento",   # Depende de projeto e financiador
        
        # Tabelas de relacionamento muitos-para-muitos
        "proj_func",       # Depende de projeto e funcionario
        "proj_esp",        # Depende de projeto e especie
        "proj_cat",        # Depende de projeto e categoria
        "registro_de_uso", # Depende de funcionario e equipamento
        
        # Tabelas que dependem de especime (por último)
        "midia"            # Depende de especime
    ]
    
    # Filtra apenas tabelas que existem no banco (comparação case-insensitive)
    tabelas_ordenadas = []
    for tabela_ordem in ordem:
        if tabela_ordem in tabelas_existentes:
            tabelas_ordenadas.append(tabelas_existentes[tabela_ordem])  # Usa o nome real da tabela
    
    # Verifica se alguma tabela essencial está faltando
    tabelas_faltando = [t for t in ordem if t not in tabelas_existentes]
    if tabelas_faltando:
        print(f"\n⚠️  AVISO: {len(tabelas_faltando)} tabelas não encontradas no banco:")
        for tabela in tabelas_faltando[:5]:  # Mostra apenas as primeiras 5
            print(f"   - {tabela.upper()}")
        if len(tabelas_faltando) > 5:
            print(f"   ... e mais {len(tabelas_faltando) - 5} tabelas")
        print("\n💡 Considerações:")
        print("   - Essas tabelas podem estar faltando no script.sql")
        print("   - Ou podem ter nomes diferentes do esperado")
        print("   - A população continuará apenas com as tabelas existentes")
        
        continuar = input("\nDeseja continuar mesmo assim? (s/N): ").strip().lower()
        if continuar not in ['s', 'sim', 'y', 'yes']:
            print("⚠️  Operação cancelada pelo usuário.")
            return 0, 1
    
    print(f"\nIniciando população de {len(tabelas_ordenadas)} tabelas...")
    print(f"Ordem de execução: {' → '.join([t.upper() for t in tabelas_ordenadas])}")

    sucessos_totais = 0
    erros_totais = 0
    tabelas_processadas = 0
    contexto_global = {}  # Contexto global das tabelas populadas

    for tabela_nome in tabelas_ordenadas:
        print(f"\n{'='*70}")
        print(f"Processando tabela: `{tabela_nome.upper()}`")
        
        try:
            # Verifica se a tabela já tem dados
            cursor = conexao.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_nome}`")
            total_existente = cursor.fetchone()[0]
            cursor.close()
            
            if total_existente > 0:
                print(f"Tabela `{tabela_nome.upper()}` já contém {total_existente} registros.")
                # Adiciona dados existentes ao contexto (usando nome em minúsculo)
                contexto_global[tabela_nome.lower()] = get_table_data_for_context(conexao, tabela_nome, 10)
                continue
            
            # TRATAMENTO ESPECIAL PARA TABELA TAXON
            if tabela_nome.lower() == 'taxon':
                print("Aplicando tratamento especial para a tabela `Taxon`...")
                resultado = populate_taxon_table(conexao, n_especies)
                if resultado:
                    sucessos_totais += 1
                    tabelas_processadas += 1
                    contexto_global[tabela_nome.lower()] = get_table_data_for_context(conexao, tabela_nome, 10)
                else:
                    erros_totais += 1
                continue

            # TRATAMENTO ESPECIAL PARA TABELA MIDIA  
            if tabela_nome.lower() == 'midia':
                print("Preenchendo tabela `Midia` com imagens reais...")
                resultado = populate_midia_table_v2(conexao, contexto_global)
                if resultado:
                    sucessos_totais += 1
                    tabelas_processadas += 1
                    contexto_global[tabela_nome.lower()] = get_table_data_for_context(conexao, tabela_nome, 10)
                else:
                    erros_totais += 1
                continue

            # VERIFICAÇÃO DE DEPENDÊNCIAS ANTES DE GERAR DADOS
            dependencias_ok = verify_dependencies_v2(conexao, tabela_nome, contexto_global)
            if not dependencias_ok:
                print(f"Pulando `{tabela_nome.upper()}`: dependências não atendidas")
                erros_totais += 1
                continue

            # GERAÇÃO DE DADOS COM CONTEXTO INTELIGENTE
            print(f"Gerando dados com contexto semântico...")
            
            # Calcula número de linhas baseado nas dependências
            n_linhas_ajustado = calculate_optimal_rows(conexao, tabela_nome, n_linhas, contexto_global)
            
            if n_linhas_ajustado == 0:
                print(f"Número de linhas ajustado para 0 - pulando tabela")
                continue
            
            # Gera dados com retry melhorado
            dados_gerados = generate_table_data_with_context(
                conexao, tabela_nome, n_linhas_ajustado, schema, contexto_global
            )
            
            if not dados_gerados:
                print(f"Falha ao gerar dados para `{tabela_nome.upper()}`")
                erros_totais += 1
                continue
            
            # Insere os dados com validação de FK
            print(f"Inserindo {len(dados_gerados['registros'])} registros...")
            resultado_insercao = insert_data_from_json(conexao, tabela_nome, dados_gerados)
            
            if resultado_insercao is not False:
                print(f"✅ Tabela `{tabela_nome.upper()}` processada com sucesso")
                sucessos_totais += 1
                tabelas_processadas += 1
                # Atualiza contexto com dados recém-inseridos (usando nome em minúsculo)
                contexto_global[tabela_nome.lower()] = get_table_data_for_context(conexao, tabela_nome, 10)
            else:
                print(f"❌ Falha na inserção para `{tabela_nome.upper()}`")
                erros_totais += 1
                
        except (mysql.connector.Error, ValueError, KeyError, TypeError) as e:
            print(f"❌ Erro crítico ao processar `{tabela_nome.upper()}`: {e}")
            erros_totais += 1
            continue
    
    # Relatório final
    print(f"\n{'='*70}")
    print("RELATÓRIO FINAL DA POPULAÇÃO DE TABELAS")
    print(f"{'='*70}")
    print(f"Tabelas processadas com sucesso: {sucessos_totais}")
    print(f"Tabelas com erro: {erros_totais}")
    print(f"Total de tabelas processadas: {tabelas_processadas}")
    print(f"Taxa de sucesso: {(sucessos_totais/(sucessos_totais+erros_totais)*100):.1f}%" if (sucessos_totais+erros_totais) > 0 else "N/A")
    print(f"{'='*70}")
    
    return sucessos_totais, erros_totais


def verify_dependencies(conexao, tabela_nome, schema):
    """
    Verifica se as dependências de uma tabela estão satisfeitas antes de popular.
    """
    dependencias = {
        'hierarquia': ['taxon'],
        'especie': ['taxon'],
        'especime': ['especie'],
        'amostra': ['especie', 'local_de_coleta'],
        'midia': ['especime'],
        'artigo': ['projeto'],
        'proj_func': ['projeto', 'funcionario'],
        'proj_esp': ['projeto', 'especie'],
        'proj_cat': ['projeto', 'categoria'],
        'contrato': ['funcionario', 'laboratorio'],
        'financiamento': ['projeto', 'financiador'],
        'registro_de_uso': ['funcionario', 'equipamento']
    }
    
    if tabela_nome not in dependencias:
        return True  # Tabela sem dependências
    
    cursor = conexao.cursor()
    try:
        for tabela_dependencia in dependencias[tabela_nome]:
            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_dependencia}`")
            count = cursor.fetchone()[0]
            if count == 0:
                print(f"Dependência não atendida: tabela `{tabela_dependencia.upper()}` está vazia")
                return False
        return True
    except mysql.connector.Error as e:
        print(f"Erro ao verificar dependências: {e}")
        return False
    finally:
        cursor.close()


def adjust_row(conexao, tabela_nome, n_linhas_original):
    """
    Ajusta o número de linhas baseado nas dependências disponíveis.
    Versão melhorada que considera múltiplas dependências.
    """
    # Mapeamento de dependências múltiplas
    dependencias_multiplas = {
        'especime': ['especie'],
        'amostra': ['especie', 'local_de_coleta'], 
        'midia': ['especime'],
        'artigo': ['projeto'],
        'proj_func': ['projeto', 'funcionario'],
        'proj_esp': ['projeto', 'especie'],
        'proj_cat': ['projeto', 'categoria'],
        'contrato': ['funcionario', 'laboratorio'],
        'financiamento': ['projeto', 'financiador'],
        'registro_de_uso': ['funcionario', 'equipamento']
    }
    
    if tabela_nome not in dependencias_multiplas:
        return n_linhas_original
    
    cursor = conexao.cursor()
    try:
        dependencias = dependencias_multiplas[tabela_nome]
        min_registros = []
        
        # Verifica o número de registros em cada tabela dependente
        for tabela_dep in dependencias:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM `{tabela_dep}`")
                count = cursor.fetchone()[0]
                min_registros.append(count)
                print(f"Tabela `{tabela_dep.upper()}` tem {count} registros disponíveis")
            except mysql.connector.Error as e:
                # Se a tabela não existe, assume 0
                print(f"Erro ao acessar tabela {tabela_dep}: {e}")
                min_registros.append(0)
        
        if not min_registros or min(min_registros) == 0:
            print(f"Nenhum registro disponível nas dependências de {tabela_nome.upper()}")
            return 0
        
        # Para tabelas de relacionamento (muitos-para-muitos), permite mais combinações
        if tabela_nome.startswith('proj_'):
            # Permite até o produto das tabelas relacionadas, mas com limite razoável
            limite_max = min(min_registros[0] * min_registros[1], n_linhas_original * 3)
        else:
            # Para outras tabelas, limita baseado na menor dependência
            limite_max = min(min_registros) * 2  # Permite até 2x o menor número
        
        limite = min(n_linhas_original, max(1, limite_max))
        
        if limite != n_linhas_original:
            print(f"Ajustando número de linhas de {n_linhas_original} para {limite} (baseado em dependências)")
        
        return limite
        
    except mysql.connector.Error as e:
        print(f"Erro ao ajustar número de linhas para {tabela_nome}: {e}")
        return n_linhas_original
    finally:
        cursor.close()


def validate_structure(registros, schema_colunas):
    """
    Valida se os registros têm a estrutura esperada baseada no schema.
    """
    if not registros or not isinstance(registros, list):
        return False
    
    if not schema_colunas:
        return True  # Se não temos schema, aceita qualquer estrutura
    
    # Pega os nomes das colunas esperadas
    colunas_esperadas = {col['nome'] for col in schema_colunas}
    
    # Verifica o primeiro registro como amostra
    primeiro_registro = registros[0]
    if not isinstance(primeiro_registro, dict):
        return False
    
    colunas_recebidas = set(primeiro_registro.keys())
    
    # Verifica se pelo menos 50% das colunas esperadas estão presentes
    intersecao = colunas_esperadas.intersection(colunas_recebidas)
    cobertura = len(intersecao) / len(colunas_esperadas) if colunas_esperadas else 1
    
    return cobertura >= 0.5


def get_available_foreign_keys(conexao, tabela_nome):
    """
    Obtém os valores disponíveis de chaves estrangeiras para uma tabela específica.
    """
    fk_mappings = {
        'hierarquia': {
            'ID_Tax': 'SELECT ID_Tax, Tipo, Nome FROM Taxon ORDER BY ID_Tax',
            'ID_TaxTopo': 'SELECT ID_Tax, Tipo, Nome FROM Taxon ORDER BY ID_Tax'
        },
        'especie': {
            'ID_Gen': 'SELECT ID_Tax, Nome FROM Taxon WHERE Tipo = "Gênero" ORDER BY ID_Tax'
        },
        'especime': {
            'ID_Esp': 'SELECT ID_Esp, Nome FROM Especie ORDER BY ID_Esp'
        },
        'amostra': {
            'ID_Esp': 'SELECT ID_Esp, Nome FROM Especie ORDER BY ID_Esp',
            'ID_Local': 'SELECT ID_Local, Nome FROM Local_de_Coleta ORDER BY ID_Local'
        },
        'midia': {
            'ID_Especime': 'SELECT ID_Especime, Descritivo FROM Especime ORDER BY ID_Especime'
        },
        'artigo': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj'
        },
        'proj_func': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj',
            'ID_Func': 'SELECT ID_Func, Nome FROM Funcionario ORDER BY ID_Func'
        },
        'proj_esp': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj',
            'ID_Esp': 'SELECT ID_Esp, Nome FROM Especie ORDER BY ID_Esp'
        },
        'proj_cat': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj',
            'ID_Categ': 'SELECT ID_Categ, Descritivo FROM Categoria ORDER BY ID_Categ'
        },
        'contrato': {
            'ID_Func': 'SELECT ID_Func, Nome FROM Funcionario ORDER BY ID_Func',
            'ID_Lab': 'SELECT ID_Lab, Nome FROM Laboratorio ORDER BY ID_Lab'
        },
        'financiamento': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj',
            'ID_Financiador': 'SELECT ID_Financiador, Descritivo FROM Financiador ORDER BY ID_Financiador'
        },
        'registro_de_uso': {
            'ID_Func': 'SELECT ID_Func, Nome FROM Funcionario ORDER BY ID_Func',
            'ID_Equip': 'SELECT ID_Equip, Tipo, Modelo FROM Equipamento ORDER BY ID_Equip'
        }
    }
    
    if tabela_nome not in fk_mappings:
        return {}
    
    cursor = conexao.cursor()
    foreign_keys_data = {}
    
    try:
        for campo, query in fk_mappings[tabela_nome].items():
            cursor.execute(query)
            resultados = cursor.fetchall()
            foreign_keys_data[campo] = resultados
            
        return foreign_keys_data
        
    except mysql.connector.Error as e:
        print(f"Erro ao obter FKs para {tabela_nome}: {e}")
        return {}
    finally:
        cursor.close()


def get_existing_data_for_context(conexao, tabelas_ja_populadas, limite_por_tabela=5):
    """
    Obtém dados das tabelas já populadas para usar como contexto na geração de novos dados.
    """
    contexto_dados = {}
    cursor = conexao.cursor()
    
    for tabela in tabelas_ja_populadas:
        try:
            # Busca alguns registros de exemplo de cada tabela
            cursor.execute(f"SELECT * FROM `{tabela}` LIMIT {limite_por_tabela}")
            registros = cursor.fetchall()
            
            if registros:
                # Obtém os nomes das colunas
                cursor.execute(f"DESCRIBE `{tabela}`")
                colunas = [col[0] for col in cursor.fetchall()]
                
                # Converte para formato legível
                registros_dict = []
                for registro in registros:
                    registro_dict = {}
                    for i, valor in enumerate(registro):
                        # Trata campos BLOB (converte para texto indicativo)
                        if isinstance(valor, bytes):
                            registro_dict[colunas[i]] = f"<BLOB:{len(valor)}bytes>"
                        else:
                            registro_dict[colunas[i]] = valor
                    registros_dict.append(registro_dict)
                
                contexto_dados[tabela] = registros_dict
                
        except mysql.connector.Error as e:
            print(f"Erro ao obter dados de {tabela}: {e}")
            continue
    
    cursor.close()
    return contexto_dados


def get_table_data_for_context(conexao, tabela_nome, limite=10):
    """
    Obtém dados de uma tabela específica para usar como contexto.
    """
    cursor = conexao.cursor()
    try:
        cursor.execute(f"SELECT * FROM `{tabela_nome}` LIMIT {limite}")
        registros = cursor.fetchall()
        
        if not registros:
            return []
        
        # Obtém os nomes das colunas
        cursor.execute(f"DESCRIBE `{tabela_nome}`")
        colunas = [col[0] for col in cursor.fetchall()]
        
        # Converte para formato legível
        registros_dict = []
        for registro in registros:
            registro_dict = {}
            for i, valor in enumerate(registro):
                if isinstance(valor, bytes):
                    registro_dict[colunas[i]] = f"<BLOB:{len(valor)}bytes>"
                else:
                    registro_dict[colunas[i]] = valor
            registros_dict.append(registro_dict)
        
        return registros_dict
        
    except mysql.connector.Error as e:
        print(f"Erro ao obter dados de {tabela_nome}: {e}")
        return []
    finally:
        cursor.close()


def verify_dependencies_v2(conexao, tabela_nome, contexto_global):
    """
    Versão melhorada que verifica dependências usando o contexto global.
    """
    dependencias = {
        'hierarquia': ['taxon'],
        'especie': ['taxon'],
        'especime': ['especie'],
        'amostra': ['especie', 'local_de_coleta'],
        'midia': ['especime'],
        'artigo': ['projeto'],
        'proj_func': ['projeto', 'funcionario'],
        'proj_esp': ['projeto', 'especie'],
        'proj_cat': ['projeto', 'categoria'],
        'contrato': ['funcionario', 'laboratorio'],
        'financiamento': ['projeto', 'financiador'],
        'registro_de_uso': ['funcionario', 'equipamento']
    }
    
    if tabela_nome.lower() not in dependencias:
        return True  # Tabela sem dependências
    
    # Obtém lista de tabelas existentes do banco
    cursor = conexao.cursor()
    try:
        cursor.execute("SHOW TABLES")
        tabelas_banco = cursor.fetchall()
        tabelas_existentes = {nome[0].lower(): nome[0] for nome in tabelas_banco}
        
        for tabela_dep in dependencias[tabela_nome.lower()]:
            # Primeiro verifica se a tabela está no contexto
            if tabela_dep in contexto_global and contexto_global[tabela_dep]:
                continue
            
            # Verifica se a tabela existe no banco (case-insensitive)
            nome_real_tabela = tabelas_existentes.get(tabela_dep.lower())
            if not nome_real_tabela:
                print(f"Dependência não atendida: tabela `{tabela_dep.upper()}` não existe")
                return False
            
            # Verifica se tem dados
            cursor.execute(f"SELECT COUNT(*) FROM `{nome_real_tabela}`")
            count = cursor.fetchone()[0]
            if count == 0:
                print(f"Dependência não atendida: tabela `{tabela_dep.upper()}` está vazia")
                return False
        
        return True
    except mysql.connector.Error as e:
        print(f"Erro ao verificar dependências: {e}")
        return False
    finally:
        cursor.close()


def populate_taxon_table(conexao, n_especies=250):
    """Popula a tabela Taxon com hierarquia taxonômica válida."""
    try:
        print("Gerando taxonomia completa via IA...")
        
        prompt = f"""
Gere taxonomia para {n_especies} espécies de laboratório científico.

IMPORTANTE: Use EXATAMENTE estes tipos (sem acentos):
- Dominio
- Reino  
- Filo
- Classe
- Ordem
- Familia
- Genero

Estrutura hierárquica:
- 1 Domínio (Eukarya)
- 2-3 Reinos (Animalia, Plantae, Fungi)
- 5-8 Filos
- 10-15 Classes
- 20-30 Ordens
- 40-60 Famílias
- Gêneros suficientes para as espécies

Formato JSON:
{{
    "registros": [
        {{"ID_Tax": 1, "Tipo": "Dominio", "Nome": "Eukarya"}},
        {{"ID_Tax": 2, "Tipo": "Reino", "Nome": "Animalia"}}
    ]
}}

RESPONDA APENAS COM O JSON.
"""
        
        resposta = generate_data(prompt, modelo="gpt-4o-mini", temperatura=0.3)
        
        if not resposta:
            print("Erro: IA não retornou dados")
            return False
        
        resposta_limpa = clean_json_response(resposta)
        dados_json = json.loads(resposta_limpa)
        
        if not isinstance(dados_json, dict) or "registros" not in dados_json:
            print("Erro: estrutura JSON inválida")
            return False
        
        registros = dados_json["registros"]
        if not registros:
            print("Erro: nenhum registro encontrado")
            return False
        
        # Valida e insere os dados
        cursor = conexao.cursor()
        tipos_validos = {'Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero'}
        registros_validos = []
        
        for item in registros:
            if (isinstance(item, dict) and 
                all(k in item for k in ['Tipo', 'Nome', 'ID_Tax']) and
                item['Tipo'] in tipos_validos):
                
                registros_validos.append((
                    item['ID_Tax'],
                    item['Tipo'],
                    str(item['Nome'])[:50]  # Trunca se necessário
                ))
        
        if not registros_validos:
            print("Erro: nenhum registro válido encontrado")
            return False
        
        # Insere os dados
        query = "INSERT INTO Taxon (ID_Tax, Tipo, Nome) VALUES (%s, %s, %s)"
        cursor.executemany(query, registros_validos)
        conexao.commit()
        cursor.close()
        
        print(f"Taxonomia inserida: {len(registros_validos)} registros")
        return True
        
    except (json.JSONDecodeError, mysql.connector.Error, ValueError, KeyError) as e:
        print(f"Erro ao popular Taxon: {e}")
        return False  


def populate_midia_table(conexao, delay_entre_requisicoes=1):
    """Popula a tabela Midia com imagens das espécies."""
    cursor = conexao.cursor()
    
    try:
        # Verifica dependências
        cursor.execute("SELECT COUNT(*) FROM Especime")
        count_especime = cursor.fetchone()[0]
        
        if count_especime == 0:
            print("Nenhum espécime encontrado. Tabela Especime deve ser populada primeiro.")
            return False
        
        print(f"Processando {count_especime} espécimes para mídia...")
        
        # Busca espécimes com suas espécies
        cursor.execute("""
            SELECT e.ID_Especime, s.Nome, s.Nome_Pop, s.Descricao 
            FROM Especime e 
            JOIN Especie s ON e.ID_Esp = s.ID_Esp 
            LIMIT 15
        """)
        especimes = cursor.fetchall()
        
        if not especimes:
            print("Erro ao buscar espécimes com espécies")
            return False
        
        sucessos = 0
        falhas = 0
        
        for idx, (id_especime, nome_especie, nome_popular, descricao) in enumerate(especimes, 1):
            print(f"  [{idx}/{len(especimes)}] Processando: {nome_especie}")
            
            # Tenta buscar imagem
            imagem_bytes = search_image_web_improved(nome_especie, timeout=8)
            termo_usado = "web"
            
            # Se não encontrou, cria placeholder
            if not imagem_bytes:
                print(f"    Criando placeholder para: {nome_especie}")
                imagem_bytes = create_placeholder_image_improved(nome_especie, nome_popular, descricao)
                termo_usado = "placeholder"
            
            if imagem_bytes:
                try:
                    # Tipo descritivo
                    tipo_midia = f"{'Placeholder' if termo_usado == 'placeholder' else 'Foto científica'} - {nome_especie}"
                    
                    cursor.execute(
                        "INSERT INTO Midia (ID_Especime, Tipo, Dado) VALUES (%s, %s, %s)",
                        (id_especime, tipo_midia[:50], imagem_bytes)
                    )
                    sucessos += 1
                    print(f"    ✅ Mídia inserida ({termo_usado})")
                except mysql.connector.Error as e:
                    print(f"    ❌ Erro DB: {e}")
                    falhas += 1
            else:
                falhas += 1
                print(f"    ❌ Falha total para {nome_especie}")
            
            # Delay entre requisições
            if idx < len(especimes):
                time.sleep(delay_entre_requisicoes)
        
        conexao.commit()
        print(f"\n📊 Mídia: ✅ {sucessos} sucessos, ❌ {falhas} falhas")
        print(f"Taxa de sucesso: {(sucessos/(sucessos+falhas)*100):.1f}%" if (sucessos+falhas) > 0 else "N/A")
        
        return sucessos > 0
        
    except mysql.connector.Error as e:
        print(f"Erro ao popular Midia: {e}")
        return False
    finally:
        cursor.close()


def generate_sql_query(user_prompt, schema, modelo="gpt-4o-mini", temperatura=0.3):
    """Gera query SQL baseada em pedido do usuário respeitando o schema."""
    if not schema:
        print("Schema não fornecido para geração de SQL")
        return None
    
    # Identifica tabelas relevantes no prompt
    texto = user_prompt.lower()
    tabelas_relevantes = []
    
    # Palavras-chave para identificar tabelas
    palavras_chave = {
        'especie': ['Especie', 'Especime'], 'taxonomia': ['Taxon', 'Hierarquia'],
        'projeto': ['Projeto', 'Artigo'], 'funcionario': ['Funcionario', 'Contrato'],
        'laboratorio': ['Laboratorio'], 'midia': ['Midia'], 'amostra': ['Amostra'],
        'financiamento': ['Financiamento'], 'equipamento': ['Equipamento']
    }
    
    for palavra, tabelas in palavras_chave.items():
        if palavra in texto:
            tabelas_relevantes.extend(tabelas)
    
    # Busca nomes exatos de tabelas
    for tabela_nome in schema.keys():
        if tabela_nome.lower() in texto:
            tabelas_relevantes.append(tabela_nome)
    
    # Remove duplicatas e filtra tabelas existentes
    tabelas_relevantes = list(set(t for t in tabelas_relevantes if t in schema))
    
    if not tabelas_relevantes:
        tabelas_relevantes = ['Especie', 'Taxon', 'Projeto', 'Funcionario']  # Padrão
    
    # Monta schema simplificado
    schema_info = []
    for tabela in tabelas_relevantes:
        if tabela in schema:
            colunas = [f"{col['nome']} ({col['tipo']})" for col in schema[tabela]]
            schema_info.append(f"{tabela}: {', '.join(colunas)}")
    
    # Relacionamentos principais
    relacionamentos = """
RELACIONAMENTOS PRINCIPAIS:
- Especie.ID_Gen → Taxon.ID_Tax (gênero)
- Especime.ID_Esp → Especie.ID_Esp 
- Midia.ID_Especime → Especime.ID_Especime
- Contrato.ID_Func → Funcionario.ID_Func
- Artigo.ID_Proj → Projeto.ID_Proj
"""
    
    prompt = f"""
Sistema de taxonomia científica. Gere SQL para: "{user_prompt}"

SCHEMA:
{chr(10).join(schema_info)}

{relacionamentos}

REGRAS:
1. Use APENAS tabelas/colunas do schema acima
2. Para buscar nomes específicos: use LIKE '%palavra%'
3. Use JOINs corretos baseados nos relacionamentos
4. Para Status: use valores ['Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']
5. Para IUCN: use ['LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX']
6. Para Tipo em Taxon: use ['Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero']
7. Use LIMIT 20 para listas grandes

RESPONDA APENAS COM A QUERY SQL (uma linha, sem explicações):
"""
    
    resposta = generate_data(prompt, modelo=modelo, temperatura=temperatura)
    
    if resposta:
        # Limpeza da resposta
        resposta_limpa = re.sub(r'```sql\s*', '', resposta.strip(), flags=re.IGNORECASE)
        resposta_limpa = re.sub(r'```\s*', '', resposta_limpa)
        resposta_limpa = re.sub(r'\n+', ' ', resposta_limpa)
        resposta_limpa = re.sub(r'\s+', ' ', resposta_limpa).strip()
        
        # Verifica se contém palavras SQL essenciais
        palavras_sql = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'SHOW', 'DESCRIBE']
        if any(palavra in resposta_limpa.upper() for palavra in palavras_sql):
            return resposta_limpa
    
    print("Falha ao gerar query SQL válida")
    return None


def make_query(conexao, sql_query):
    """Executa consulta SQL e exibe resultados formatados."""
    cursor = conexao.cursor()
    
    try:
        cursor.execute(sql_query)
        resultados = cursor.fetchall()
        colunas = [desc[0] for desc in cursor.description]

        if resultados:
            print(f"\n📋 Resultados da query:")
            print(f"┌─ {sql_query}")
            print("└─ Dados:")
            for i, linha in enumerate(resultados, 1):
                registro = dict(zip(colunas, linha))
                print(f"   {i}. {registro}")
        else:
            print("❌ Nenhum resultado encontrado.")
            
    except mysql.connector.Error as err:
        print(f"❌ Erro na query: {err}")
    finally:
        cursor.close()


def calculate_optimal_rows(conexao, tabela_nome, n_linhas_base, contexto_global):
    """
    Calcula o número ótimo de linhas baseado nas dependências e contexto.
    """
    dependencias = {
        'especime': ['especie'],
        'amostra': ['especie', 'local_de_coleta'], 
        'midia': ['especime'],
        'artigo': ['projeto'],
        'proj_func': ['projeto', 'funcionario'],
        'proj_esp': ['projeto', 'especie'],
        'proj_cat': ['projeto', 'categoria'],
        'contrato': ['funcionario', 'laboratorio'],
        'financiamento': ['projeto', 'financiador'],
        'registro_de_uso': ['funcionario', 'equipamento']
    }
    
    if tabela_nome.lower() not in dependencias:
        return n_linhas_base
    
    min_disponivel = float('inf')
    cursor = conexao.cursor()
    
    try:
        # Obtém lista de tabelas existentes do banco
        cursor.execute("SHOW TABLES")
        tabelas_banco = cursor.fetchall()
        tabelas_existentes = {nome[0].lower(): nome[0] for nome in tabelas_banco}
        
        for tabela_dep in dependencias[tabela_nome.lower()]:
            # Tenta primeiro do contexto, depois do banco
            if tabela_dep in contexto_global and contexto_global[tabela_dep]:
                count = len(contexto_global[tabela_dep])
            else:
                # Encontra nome real da tabela no banco
                nome_real_tabela = tabelas_existentes.get(tabela_dep.lower())
                if nome_real_tabela:
                    cursor.execute(f"SELECT COUNT(*) FROM `{nome_real_tabela}`")
                    count = cursor.fetchone()[0]
                else:
                    count = 0
            
            min_disponivel = min(min_disponivel, count)
            print(f"Tabela `{tabela_dep.upper()}` tem {count} registros disponíveis")
        
        if min_disponivel == 0:
            return 0
        
        # Para tabelas de relacionamento muitos-para-muitos
        if tabela_nome.lower().startswith('proj_'):
            # Permite mais combinações para tabelas de relacionamento
            return min(n_linhas_base * 2, min_disponivel)
        else:
            # Para outras tabelas, limita baseado na menor dependência
            return min(n_linhas_base, min_disponivel)
        
    except mysql.connector.Error as e:
        print(f"Erro ao calcular linhas ótimas: {e}")
        return n_linhas_base
    finally:
        cursor.close()


def generate_table_data_with_context(conexao, tabela_nome, n_linhas, schema, contexto_global):
    """
    Gera dados para uma tabela usando contexto das tabelas já populadas.
    """
    print(f"Gerando {n_linhas} registros para {tabela_nome} com contexto...")
    
    # Obtém chaves estrangeiras válidas
    foreign_keys = get_valid_foreign_keys(conexao, tabela_nome, contexto_global)
    
    # Constrói prompt com contexto
    prompt = build_contextual_prompt(schema, tabela_nome, n_linhas, contexto_global, foreign_keys)
    
    # Gera dados com retry
    max_tentativas = 3
    for tentativa in range(1, max_tentativas + 1):
        try:
            print(f"Tentativa {tentativa}/{max_tentativas}")
            resposta = generate_data(prompt)
            
            if not resposta or not resposta.strip():
                continue
            
            # Limpa e parse da resposta
            resposta_limpa = clean_json_response(resposta)
            dados_json = json.loads(resposta_limpa)
            
            if not isinstance(dados_json, dict) or "registros" not in dados_json:
                continue
            
            registros = dados_json["registros"]
            if not registros:
                continue
            
            # Valida e corrige FKs
            registros_corrigidos = validate_and_fix_foreign_keys(registros, foreign_keys)
            dados_json["registros"] = registros_corrigidos
            
            return dados_json
            
        except (json.JSONDecodeError, ValueError, Exception) as e:
            print(f"Erro na tentativa {tentativa}: {e}")
            if tentativa < max_tentativas:
                time.sleep(2)
    
    return None


def get_valid_foreign_keys(conexao, tabela_nome, contexto_global):
    """
    Obtém chaves estrangeiras válidas para uma tabela.
    """
    foreign_keys = {}
    
    # Mapeamento de campos FK para tabelas
    fk_mapping = {
        'hierarquia': {'ID_Tax': 'taxon', 'ID_TaxTopo': 'taxon'},
        'especie': {'ID_Gen': 'taxon'},
        'especime': {'ID_Esp': 'especie'},
        'amostra': {'ID_Esp': 'especie', 'ID_Local': 'local_de_coleta'},
        'midia': {'ID_Especime': 'especime'},
        'artigo': {'ID_Proj': 'projeto'},
        'proj_func': {'ID_Proj': 'projeto', 'ID_Func': 'funcionario'},
        'proj_esp': {'ID_Proj': 'projeto', 'ID_Esp': 'especie'},
        'proj_cat': {'ID_Proj': 'projeto', 'ID_Categ': 'categoria'},
        'contrato': {'ID_Func': 'funcionario', 'ID_Lab': 'laboratorio'},
        'financiamento': {'ID_Proj': 'projeto', 'ID_Financiador': 'financiador'},
        'registro_de_uso': {'ID_Func': 'funcionario', 'ID_Equip': 'equipamento'},
        'equipamento': {'ID_Lab': 'laboratorio'}
    }
    
    if tabela_nome.lower() not in fk_mapping:
        return foreign_keys
    
    cursor = conexao.cursor()
    try:
        # Obtém lista de tabelas existentes do banco
        cursor.execute("SHOW TABLES")
        tabelas_banco = cursor.fetchall()
        tabelas_existentes = {nome[0].lower(): nome[0] for nome in tabelas_banco}
        
        for campo_fk, tabela_ref in fk_mapping[tabela_nome.lower()].items():
            # Tenta obter IDs válidos do contexto primeiro
            if tabela_ref in contexto_global and contexto_global[tabela_ref]:
                # Obtém os IDs do contexto
                registros_contexto = contexto_global[tabela_ref]
                # Identifica o campo ID principal
                id_field = get_primary_key_field(tabela_ref)
                if id_field:
                    ids_validos = [r[id_field] for r in registros_contexto if id_field in r]
                    if ids_validos:
                        foreign_keys[campo_fk] = ids_validos
                        continue
            
            # Se não conseguiu do contexto, busca do banco
            nome_real_tabela = tabelas_existentes.get(tabela_ref.lower())
            if nome_real_tabela:
                id_field = get_primary_key_field(tabela_ref)
                if id_field:
                    cursor.execute(f"SELECT {id_field} FROM `{nome_real_tabela}` ORDER BY {id_field}")
                    ids = [row[0] for row in cursor.fetchall()]
                    if ids:
                        foreign_keys[campo_fk] = ids
    
    except mysql.connector.Error as e:
        print(f"Erro ao obter FKs para {tabela_nome}: {e}")
    finally:
        cursor.close()
    
    return foreign_keys


def get_primary_key_field(tabela_nome):
    """
    Retorna o nome do campo da chave primária de uma tabela.
    """
    pk_mapping = {
        'taxon': 'ID_Tax',
        'especie': 'ID_Esp',
        'especime': 'ID_Especime',
        'local_de_coleta': 'ID_Local',
        'projeto': 'ID_Proj',
        'funcionario': 'ID_Func',
        'categoria': 'ID_Categ',
        'laboratorio': 'ID_Lab',
        'financiador': 'ID_Financiador',
        'equipamento': 'ID_Equip',
        'amostra': 'ID_Amos',
        'midia': 'ID_Midia',
        'artigo': 'ID_Artigo',
        'contrato': 'ID_Contrato',
        'financiamento': 'ID_Financiamento'
    }
    return pk_mapping.get(tabela_nome.lower())


def build_contextual_prompt(schema, tabela_nome, n_linhas, contexto_global, foreign_keys):
    """
    Constrói um prompt contextual para geração de dados.
    """
    # Obtém informações da tabela
    colunas_info = schema.get(tabela_nome, [])
    colunas_str = ", ".join([f"{col['nome']} ({col['tipo']})" for col in colunas_info])
    
    # Constrói contexto das outras tabelas
    contexto_str = ""
    if contexto_global:
        contexto_str = "\nCONTEXTO DAS TABELAS EXISTENTES:\n"
        for tab, registros in contexto_global.items():
            if registros:
                contexto_str += f"\n{tab.upper()}:\n"
                for i, reg in enumerate(registros[:3]):  # Mostra apenas 3 exemplos
                    contexto_str += f"  {reg}\n"
                if len(registros) > 3:
                    contexto_str += f"  ... e mais {len(registros)-3} registros\n"
    
    # Constrói informações de FK
    fk_str = ""
    if foreign_keys:
        fk_str = "\nCHAVES ESTRANGEIRAS VÁLIDAS:\n"
        for campo, valores in foreign_keys.items():
            fk_str += f"- {campo}: {valores[:10]}{'...' if len(valores) > 10 else ''}\n"
    
    # Constraints específicas por tabela
    constraints_especificas = ""
    if 'projeto' in tabela_nome.lower():
        constraints_especificas = "\n6. Para Status em Projeto: USE APENAS ['Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']"
    elif 'contrato' in tabela_nome.lower():
        constraints_especificas = "\n6. Para Status em Contrato: USE APENAS ['Pendente', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']"
    elif 'especie' in tabela_nome.lower():
        constraints_especificas = "\n6. Para IUCN: USE APENAS ['LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX']"
    
    prompt = f"""
Gere {n_linhas} registros VÁLIDOS para a tabela `{tabela_nome.upper()}` de um laboratório científico.

SCHEMA DA TABELA:
{colunas_str}
{contexto_str}
{fk_str}

INSTRUÇÕES CRÍTICAS:
1. USE APENAS valores de FK que estão listados acima
2. Mantenha COERÊNCIA SEMÂNTICA com os dados existentes
3. Use dados REALÍSTICOS para laboratório científico
4. Para datas, use formato YYYY-MM-DD
5. Para decimais, use formato 0000.00{constraints_especificas}

RESPONDA APENAS COM JSON:
{{
    "registros": [
        {{ campos da tabela }}
    ]
}}
"""
    return prompt


def validate_and_fix_foreign_keys(registros, foreign_keys):
    """
    Valida e corrige chaves estrangeiras nos registros gerados.
    """
    if not foreign_keys:
        return registros
    
    registros_corrigidos = []
    for i, registro in enumerate(registros):
        registro_corrigido = registro.copy()
        
        for campo_fk, valores_validos in foreign_keys.items():
            if campo_fk in registro_corrigido:
                valor_atual = registro_corrigido[campo_fk]
                
                # Se o valor não é válido, substitui por um válido aleatório
                if valor_atual not in valores_validos and valores_validos:
                    novo_valor = random.choice(valores_validos)
                    print(f"  ✓ Corrigindo FK no registro {i+1}: {campo_fk} {valor_atual} → {novo_valor}")
                    registro_corrigido[campo_fk] = novo_valor
        
        registros_corrigidos.append(registro_corrigido)
    
    return registros_corrigidos


def populate_midia_table_v2(conexao, contexto_global):
    """
    Versão melhorada da função de população da tabela Midia com contexto.
    """
    # Verifica se existem especimes disponíveis
    if 'especime' not in contexto_global or not contexto_global['especime']:
        print("Não há especimes disponíveis para criar mídia")
        return False
    
    # Obtém IDs de especimes válidos
    especimes = contexto_global['especime']
    ids_especimes = [esp['ID_Especime'] for esp in especimes if 'ID_Especime' in esp]
    
    if not ids_especimes:
        print("Não foi possível obter IDs de especimes válidos")
        return False
    
    # Gera registros de mídia para cada especime
    registros_midia = []
    for i, id_especime in enumerate(ids_especimes[:5]):  # Limita a 5 por enquanto
        registros_midia.append({
            "ID_Especime": id_especime,
            "Tipo": random.choice(["Foto científica", "Video comportamental", "Audio vocalização", "Documento"]),
            "Dado": None  # BLOB deve ser NULL no JSON
        })
    
    dados_json = {"registros": registros_midia}
    
    # Encontra o nome real da tabela Midia (case-insensitive)
    cursor = conexao.cursor()
    try:
        cursor.execute("SHOW TABLES")
        tabelas_banco = cursor.fetchall()
        nome_real_midia = None
        
        for (nome_tabela,) in tabelas_banco:
            if nome_tabela.lower() == 'midia':
                nome_real_midia = nome_tabela
                break
        
        if not nome_real_midia:
            print("Tabela Midia não encontrada no banco")
            return False
        
        return insert_data_from_json(conexao, nome_real_midia, dados_json)
        
    except mysql.connector.Error as e:
        print(f"Erro ao acessar tabela Midia: {e}")
        return False
    finally:
        cursor.close()

