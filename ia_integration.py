from typing import Dict, List, Optional, Any

import mysql.connector
import openai
import requests
import json
import re
import random
import time
import io
from PIL import Image, ImageDraw, ImageFont
from duckduckgo_search import DDGS

from db_operations import insert_data_from_json, get_schema_info


class DatabaseContextManager:
    """Gerencia contexto global do banco de dados para otimizar geração de dados pela IA."""
    
    def __init__(self, conexao, schema):
        self.conexao = conexao
        self.schema = schema
        self.contexto_global = {}
        self.relacionamentos = self._build_relationship_map()
        self.constraints = self._define_constraints()
        
    def _build_relationship_map(self) -> Dict[str, Dict[str, str]]:
        """Constrói mapa completo de relacionamentos FK -> PK."""
        return {
            'hierarquia': {'ID_Tax': 'taxon.ID_Tax', 'ID_TaxTopo': 'taxon.ID_Tax'},
            'especie': {'ID_Gen': 'taxon.ID_Tax'},
            'especime': {'ID_Esp': 'especie.ID_Esp'},
            'amostra': {'ID_Esp': 'especie.ID_Esp', 'ID_Local': 'local_de_coleta.ID_Local'},
            'midia': {'ID_Especime': 'especime.ID_Especime'},
            'artigo': {'ID_Proj': 'projeto.ID_Proj'},
            'contrato': {'ID_Func': 'funcionario.ID_Func', 'ID_Lab': 'laboratorio.ID_Lab'},
            'financiamento': {'ID_Proj': 'projeto.ID_Proj', 'ID_Financiador': 'financiador.ID_Financiador'},
            'equipamento': {'ID_Lab': 'laboratorio.ID_Lab'},
            'registro_de_uso': {'ID_Func': 'funcionario.ID_Func', 'ID_Equip': 'equipamento.ID_Equip'},
            'proj_func': {'ID_Proj': 'projeto.ID_Proj', 'ID_Func': 'funcionario.ID_Func'},
            'proj_esp': {'ID_Proj': 'projeto.ID_Proj', 'ID_Esp': 'especie.ID_Esp'},
            'proj_cat': {'ID_Proj': 'projeto.ID_Proj', 'ID_Categ': 'categoria.ID_Categ'}
        }
    
    def _define_constraints(self) -> Dict[str, Dict[str, List[str]]]:
        """Define constraints específicas por tabela."""
        return {
            'taxon': {'Tipo': ['Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero']},
            'especie': {'IUCN': ['LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX']},
            'projeto': {'Status': ['Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']},
            'contrato': {'Status': ['Pendente', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado']}
        }
    
    def get_available_tables(self) -> List[str]:
        """Retorna lista de tabelas existentes no banco."""
        cursor = self.conexao.cursor()
        try:
            cursor.execute("SHOW TABLES")
            return [row[0] for row in cursor.fetchall()]
        except mysql.connector.Error as e:
            print(f"Erro ao obter tabelas: {e}")
            return []
        finally:
            cursor.close()
    
    def get_table_context(self, tabela_nome: str, limite: int = 10) -> List[Dict]:
        """Obtém contexto de dados de uma tabela específica."""
        if tabela_nome.lower() in self.contexto_global:
            return self.contexto_global[tabela_nome.lower()]
        
        cursor = self.conexao.cursor()
        try:
            cursor.execute(f"SELECT * FROM `{tabela_nome}` LIMIT {limite}")
            registros = cursor.fetchall()
            
            if not registros:
                return []
            
            cursor.execute(f"DESCRIBE `{tabela_nome}`")
            colunas = [col[0] for col in cursor.fetchall()]
            
            registros_dict = []
            for registro in registros:
                registro_dict = {}
                for i, valor in enumerate(registro):
                    if isinstance(valor, bytes):
                        registro_dict[colunas[i]] = f"<BLOB:{len(valor)}bytes>"
                    else:
                        registro_dict[colunas[i]] = valor
                registros_dict.append(registro_dict)
            
            self.contexto_global[tabela_nome.lower()] = registros_dict
            return registros_dict
            
        except mysql.connector.Error as e:
            print(f"Erro ao obter contexto de {tabela_nome}: {e}")
            return []
        finally:
            cursor.close()
    
    def get_foreign_keys(self, tabela_nome: str) -> Dict[str, List[Any]]:
        """Obtém chaves estrangeiras válidas para uma tabela."""
        foreign_keys = {}
        tabela_lower = tabela_nome.lower()
        
        if tabela_lower not in self.relacionamentos:
            return foreign_keys
        
        cursor = self.conexao.cursor()
        try:
            for campo_fk, referencia in self.relacionamentos[tabela_lower].items():
                tabela_ref, campo_ref = referencia.split('.')
                
                # Contexto primeiro, depois banco
                contexto = self.get_table_context(tabela_ref)
                if contexto:
                    # Tratamento especial para especie.ID_Gen (só gêneros)
                    if tabela_lower == 'especie' and campo_fk == 'ID_Gen':
                        ids_validos = [r['ID_Tax'] for r in contexto 
                                     if r.get('Tipo') == 'Genero']
                    else:
                        ids_validos = [r[campo_ref] for r in contexto 
                                     if campo_ref in r and r[campo_ref] is not None]
                    
                    if ids_validos:
                        foreign_keys[campo_fk] = ids_validos
                
        except mysql.connector.Error as e:
            print(f"Erro ao obter FKs para {tabela_nome}: {e}")
        finally:
            cursor.close()
        
        return foreign_keys
    
    def get_comprehensive_context(self, tabela_nome: str) -> str:
        """Gera contexto abrangente para geração de dados pela IA."""
        context_parts = []
        
        # Contexto das tabelas relacionadas
        tabela_lower = tabela_nome.lower()
        if tabela_lower in self.relacionamentos:
            context_parts.append("CONTEXTO DAS TABELAS RELACIONADAS:")
            
            for campo_fk, referencia in self.relacionamentos[tabela_lower].items():
                tabela_ref = referencia.split('.')[0]
                contexto_tabela = self.get_table_context(tabela_ref, 5)
                
                if contexto_tabela:
                    context_parts.append(f"\n{tabela_ref.upper()} (para {campo_fk}):")
                    for i, reg in enumerate(contexto_tabela[:3]):
                        context_parts.append(f"  Exemplo {i+1}: {reg}")
        
        # Constraints específicas
        if tabela_lower in self.constraints:
            context_parts.append(f"\nCONSTRAINTS OBRIGATÓRIAS para {tabela_nome.upper()}:")
            for campo, valores in self.constraints[tabela_lower].items():
                context_parts.append(f"- {campo}: APENAS {valores}")
        
        # Estatísticas do banco
        context_parts.append(f"\nESTATÍSTICAS DO BANCO:")
        for tab_nome in self.get_available_tables()[:5]:
            count = self._get_table_count(tab_nome)
            context_parts.append(f"- {tab_nome}: {count} registros")
        
        return "\n".join(context_parts)
    
    def _get_table_count(self, tabela_nome: str) -> int:
        """Obtém número de registros de uma tabela."""
        cursor = self.conexao.cursor()
        try:
            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_nome}`")
            return cursor.fetchone()[0]
        except mysql.connector.Error:
            return 0
        finally:
            cursor.close()


class AIDataGenerator:
    """Classe responsável pela geração inteligente de dados usando IA."""
    
    def __init__(self, api_key: str, context_manager: DatabaseContextManager):
        self.api_key = api_key
        self.context_manager = context_manager
        openai.api_key = api_key
        
    def generate_data(self, prompt: str, modelo: str = "gpt-4o-mini", temperatura: float = 0.4) -> Optional[str]:
        """Gera dados usando OpenAI com tratamento de erros robusto."""
        if not self.api_key:
            print("Chave OpenAI não configurada")
            return None
        
        try:
            response = openai.chat.completions.create(
                model=modelo,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperatura,
                max_tokens=4000  # Aumenta limite para contexto maior
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Erro na API OpenAI: {e}")
            return None
    
    def build_enhanced_prompt(self, tabela_nome: str, n_linhas: int) -> str:
        """Constrói prompt aprimorado com contexto abrangente."""
        
        # Schema da tabela
        schema_info = []
        if tabela_nome in self.context_manager.schema:
            for col in self.context_manager.schema[tabela_nome]:
                col_info = f"{col['nome']}: {col['tipo']}"
                if col.get('chave') == 'PRI':
                    col_info += " (PRIMARY KEY)"
                elif col.get('chave') == 'MUL':
                    col_info += " (FOREIGN KEY)"
                if 'blob' in col['tipo'].lower():
                    col_info += " (sempre NULL no JSON)"
                schema_info.append(col_info)
        
        # Contexto abrangente
        contexto_completo = self.context_manager.get_comprehensive_context(tabela_nome)
        
        # FKs válidas
        foreign_keys = self.context_manager.get_foreign_keys(tabela_nome)
        fk_info = ""
        if foreign_keys:
            fk_info = "\nCHAVES ESTRANGEIRAS VÁLIDAS:\n"
            for campo, valores in foreign_keys.items():
                sample_values = valores[:15] if len(valores) > 15 else valores
                fk_info += f"- {campo}: {sample_values}\n"
                if len(valores) > 15:
                    fk_info += f"  (total: {len(valores)} valores disponíveis)\n"
        
        # Instruções específicas por tabela
        instrucoes_especificas = self._get_table_specific_instructions(tabela_nome)
        
        prompt = f"""
Sistema de laboratório científico de taxonomia. Gere {n_linhas} registros para `{tabela_nome.upper()}`.

SCHEMA DA TABELA:
{chr(10).join(schema_info)}

{contexto_completo}

{fk_info}

{instrucoes_especificas}

REGRAS GLOBAIS:
1. USE APENAS valores de FK listados acima
2. Mantenha COERÊNCIA SEMÂNTICA com dados existentes
3. CPF: 11 dígitos numéricos válidos
4. DOI: formato "10.xxxx/yyyy.zzz"
5. Datas: formato "YYYY-MM-DD" (2020-2024)
6. Valores monetários: entre 1000.00 e 50000.00
7. BLOB: sempre null no JSON
8. Nomes científicos: nomenclatura binomial válida

FORMATO OBRIGATÓRIO:
{{
    "registros": [
        {{"campo1": valor1, "campo2": "valor2"}}
    ]
}}

RESPONDA APENAS COM O JSON VÁLIDO:
"""
        return prompt.strip()
    
    def _get_table_specific_instructions(self, tabela_nome: str) -> str:
        """Retorna instruções específicas para cada tabela."""
        instrucoes = {
            'especie': """
INSTRUÇÕES ESPECÍFICAS PARA ESPÉCIE:
- Nome: use nomenclatura binomial (Genus species)
- Nome_Pop: nome popular/comum da espécie
- Caracteristicas: descrição científica realística
- Habitat: ambiente natural específico
- IUCN: status de conservação válido
""",
            'especime': """
INSTRUÇÕES ESPECÍFICAS PARA ESPÉCIME:
- Data_Coleta: entre 2020-2024
- Observacoes: notas científicas relevantes
- Mantenha coerência com espécie relacionada
""",
            'projeto': """
INSTRUÇÕES ESPECÍFICAS PARA PROJETO:
- Nome: projeto científico realístico
- Dt_Inicio/Dt_Fim: cronograma lógico
- Descricao: objetivos científicos claros
- Valor: orçamento realístico (10000-100000)
""",
            'funcionario': """
INSTRUÇÕES ESPECÍFICAS PARA FUNCIONÁRIO:
- Nome: nomes brasileiros realísticos
- CPF: números válidos (11 dígitos)
- Email: formato institucional (@lab.br)
- Tipo: Pesquisador/Técnico/Estudante
""",
            'amostra': """
INSTRUÇÕES ESPECÍFICAS PARA AMOSTRA:
- Tipo_Amostra: tecido/sangue/DNA/RNA
- Metodo_Preservacao: formalina/etanol/congelamento
- Data_Coleta: coerente com espécime
"""
        }
        
        return instrucoes.get(tabela_nome.lower(), "")
    
    def generate_table_data(self, tabela_nome: str, n_linhas: int, max_tentativas: int = 3) -> Optional[Dict]:
        """Gera dados para tabela com retry inteligente."""
        
        for tentativa in range(1, max_tentativas + 1):
            try:
                print(f"🤖 Gerando dados IA - Tentativa {tentativa}/{max_tentativas}")
                
                prompt = self.build_enhanced_prompt(tabela_nome, n_linhas)
                resposta = self.generate_data(prompt)
                
                if not resposta:
                    continue
                
                # Limpa e valida JSON
                resposta_limpa = self._clean_json_response(resposta)
                dados_json = json.loads(resposta_limpa)
                
                if not isinstance(dados_json, dict) or "registros" not in dados_json:
                    print(f"⚠️ Estrutura JSON inválida na tentativa {tentativa}")
                    continue
                
                registros = dados_json["registros"]
                if not registros or not isinstance(registros, list):
                    print(f"⚠️ Registros vazios na tentativa {tentativa}")
                    continue
                
                # Valida e corrige dados
                registros_validados = self._validate_and_fix_data(registros, tabela_nome)
                dados_json["registros"] = registros_validados
                
                print(f"✅ Gerados {len(registros_validados)} registros válidos")
                return dados_json
                
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"❌ Erro na tentativa {tentativa}: {e}")
                if tentativa < max_tentativas:
                    time.sleep(2)
        
        print(f"❌ Falha na geração após {max_tentativas} tentativas")
        return None
    
    def _clean_json_response(self, response: str) -> str:
        """Limpa resposta da IA removendo markdown e texto extra."""
        if not response:
            return response
        
        # Remove blocos markdown
        response = re.sub(r'```json\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'```\s*', '', response)
        
        # Encontra JSON válido
        start = response.find('{')
        end = response.rfind('}')
        
        if start != -1 and end != -1 and end > start:
            return response[start:end + 1]
        
        return response.strip()
    
    def _validate_and_fix_data(self, registros: List[Dict], tabela_nome: str) -> List[Dict]:
        """Valida e corrige dados gerados."""
        registros_validos = []
        constraints = self.context_manager.constraints
        foreign_keys = self.context_manager.get_foreign_keys(tabela_nome)
        
        for registro in registros:
            if not isinstance(registro, dict):
                continue
            
            registro_corrigido = {}
            
            for campo, valor in registro.items():
                # Valida constraints específicas
                if tabela_nome.lower() in constraints and campo in constraints[tabela_nome.lower()]:
                    valores_validos = constraints[tabela_nome.lower()][campo]
                    if valor not in valores_validos:
                        valor = random.choice(valores_validos)
                        print(f"  🔧 Corrigido {campo}: → {valor}")
                
                # Valida e corrige FKs
                elif campo in foreign_keys:
                    if valor not in foreign_keys[campo]:
                        if foreign_keys[campo]:
                            valor = random.choice(foreign_keys[campo])
                            print(f"  🔧 Corrigido FK {campo}: → {valor}")
                
                # Valida CPF
                elif campo == 'CPF' and valor:
                    cpf_limpo = re.sub(r'\D', '', str(valor))
                    if len(cpf_limpo) != 11:
                        valor = ''.join([str(random.randint(0, 9)) for _ in range(11)])
                        print(f"  🔧 Corrigido CPF: → {valor}")
                
                # Valida DOI
                elif campo == 'DOI' and valor:
                    if not re.match(r'^10\.\d+/.+', str(valor)):
                        valor = f"10.{random.randint(1000, 9999)}/estudo.{random.randint(2020, 2024)}"
                        print(f"  🔧 Corrigido DOI: → {valor}")
                
                # Valida datas
                elif ('data' in campo.lower() or 'dt_' in campo.lower()) and valor:
                    if not re.match(r'^\d{4}-\d{2}-\d{2}', str(valor)):
                        valor = f"202{random.randint(0,4)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
                        print(f"  🔧 Corrigida data {campo}: → {valor}")
                
                registro_corrigido[campo] = valor
            
            if registro_corrigido:
                registros_validos.append(registro_corrigido)
        
        return registros_validos


def get_openai_key():
    """Obtém a chave de API da OpenAI do arquivo de configuração."""
    # api_key_file = "/home/samuks369/Downloads/gpt-key.txt"
    api_key_file = "C:\\Users\\thoma\\Documents\\GitHub\\openai_key.txt"
    
    try:
        with open(api_key_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Arquivo de chave não encontrado: {api_key_file}")
        return None
    except IOError as e:
        print(f"Erro ao ler chave API: {e}")
        return None


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


def populate_all_tables(conexao, n_linhas=10, n_especies=20):
    """
    Função principal otimizada para popular todas as tabelas com contexto inteligente.
    """
    print(f"\n{'='*70}")
    print("🚀 INICIANDO POPULAÇÃO INTELIGENTE DE TABELAS")
    print(f"{'='*70}")
    
    # Inicializa gerenciadores
    schema = get_schema_info(conexao)
    context_manager = DatabaseContextManager(conexao, schema)
    
    api_key = get_openai_key()
    if not api_key:
        print("❌ Chave OpenAI não encontrada. Abortando...")
        return 0, 1
    
    ai_generator = AIDataGenerator(api_key, context_manager)
    
    # Verifica tabelas existentes
    tabelas_existentes = context_manager.get_available_tables()
    if not tabelas_existentes:
        print("❌ Nenhuma tabela encontrada no banco!")
        return 0, 1
    
    print(f"📊 Tabelas encontradas: {len(tabelas_existentes)}")
    print(f"🎯 Tabelas: {', '.join(tabelas_existentes)}")
    
    # Ordem de população otimizada
    ordem_execucao = [
        # Tabelas base (sem dependências)
        "taxon", "local_de_coleta", "funcionario", "categoria", 
        "laboratorio", "financiador", "projeto",
        
        # Tabelas com dependências simples
        "hierarquia", "especie", "equipamento",
        
        # Tabelas com dependências múltiplas
        "especime", "amostra", "artigo", "contrato", "financiamento",
        
        # Tabelas de relacionamento
        "proj_func", "proj_esp", "proj_cat", "registro_de_uso",
        
        # Tabela especial (por último)
        "midia"
    ]
    
    # Filtra apenas tabelas existentes
    tabelas_para_processar = []
    for tabela in ordem_execucao:
        tabela_real = next((t for t in tabelas_existentes if t.lower() == tabela.lower()), None)
        if tabela_real:
            tabelas_para_processar.append(tabela_real)
    
    print(f"📋 Ordem de execução: {' → '.join(tabelas_para_processar)}")
    
    sucessos, erros = 0, 0
    
    for idx, tabela_nome in enumerate(tabelas_para_processar, 1):
        print(f"\n{'='*50}")
        print(f"📝 [{idx}/{len(tabelas_para_processar)}] Processando: {tabela_nome.upper()}")
        print(f"{'='*50}")
        
        try:
            # Verifica se já tem dados
            count_existente = context_manager._get_table_count(tabela_nome)
            if count_existente > 0:
                print(f"✅ Tabela já possui {count_existente} registros - atualizando contexto")
                context_manager.get_table_context(tabela_nome)
                sucessos += 1
                continue
            
            # Tratamento especial para tabelas específicas
            if tabela_nome.lower() == 'taxon':
                resultado = populate_taxon_table(conexao, n_especies, ai_generator)
            elif tabela_nome.lower() == 'hierarquia':
                resultado = populate_hierarquia_table(conexao)
            elif tabela_nome.lower() == 'midia':
                resultado = populate_midia_table(conexao)
            else:
                # Geração normal com IA aprimorada
                resultado = process_regular_table(
                    conexao, tabela_nome, n_linhas, context_manager, ai_generator
                )
            
            if resultado:
                sucessos += 1
                # Atualiza contexto após inserção bem-sucedida
                context_manager.get_table_context(tabela_nome)
                print(f"✅ {tabela_nome.upper()} processada com sucesso!")
            else:
                erros += 1
                print(f"❌ Falha ao processar {tabela_nome.upper()}")
                
        except Exception as e:
            print(f"💥 Erro crítico em {tabela_nome.upper()}: {e}")
            erros += 1
    
    # Relatório final
    print(f"\n{'='*70}")
    print("📊 RELATÓRIO FINAL")
    print(f"{'='*70}")
    print(f"✅ Sucessos: {sucessos}")
    print(f"❌ Erros: {erros}")
    print(f"📈 Taxa de sucesso: {(sucessos/(sucessos+erros)*100):.1f}%" if (sucessos+erros) > 0 else "N/A")
    print(f"{'='*70}")
    
    return sucessos, erros


def process_regular_table(conexao, tabela_nome, n_linhas, context_manager, ai_generator):
    """Processa tabela regular usando IA com contexto aprimorado."""
    
    # Verifica dependências
    if not verify_dependencies_v2(conexao, tabela_nome, context_manager):
        print(f"Dependências não atendidas para {tabela_nome}")
        return False
    
    # Calcula número otimizado de linhas
    n_linhas_otimizado = calculate_optimal_rows_v2(tabela_nome, n_linhas, context_manager)
    if n_linhas_otimizado == 0:
        print("Número de linhas calculado como 0 - pulando")
        return False
    
    print(f"Gerando {n_linhas_otimizado} registros com contexto inteligente")
    
    # Gera dados com IA aprimorada
    dados_gerados = ai_generator.generate_table_data(tabela_nome, n_linhas_otimizado)
    
    if not dados_gerados:
        print("Falha na geração de dados pela IA")
        return False
    
    # Insere no banco
    print(f"Inserindo {len(dados_gerados['registros'])} registros...")
    resultado = insert_data_from_json(conexao, tabela_nome, dados_gerados)
    
    return resultado is not False


def verify_dependencies_v2(conexao, tabela_nome, context_manager):
    """Versão otimizada de verificação de dependências."""
    if tabela_nome.lower() not in context_manager.relacionamentos:
        return True  # Sem dependências
    
    for campo_fk, referencia in context_manager.relacionamentos[tabela_nome.lower()].items():
        tabela_ref = referencia.split('.')[0]
        
        # Verifica se tem dados (contexto ou banco)
        contexto = context_manager.get_table_context(tabela_ref)
        if not contexto:
            count = context_manager._get_table_count(tabela_ref)
            if count == 0:
                print(f"Dependência {tabela_ref.upper()} não atendida (vazia)")
                return False
    
    return True


def calculate_optimal_rows_v2(tabela_nome, n_linhas_base, context_manager):
    """Versão otimizada para calcular número ideal de registros."""
    tabela_lower = tabela_nome.lower()
    
    if tabela_lower not in context_manager.relacionamentos:
        return n_linhas_base
    
    min_disponivel = float('inf')
    
    for campo_fk, referencia in context_manager.relacionamentos[tabela_lower].items():
        tabela_ref = referencia.split('.')[0]
        
        # Verifica quantidade disponível
        contexto = context_manager.get_table_context(tabela_ref)
        if contexto:
            count = len(contexto)
        else:
            count = context_manager._get_table_count(tabela_ref)
        
        min_disponivel = min(min_disponivel, count)
    
    if min_disponivel == 0:
        return 0
    
    # Para tabelas de relacionamento muitos-para-muitos, permite mais registros
    if tabela_lower.startswith('proj_'):
        return min(n_linhas_base * 2, min_disponivel)
    
    return min(n_linhas_base, min_disponivel)


def populate_taxon_table(conexao, n_especies=250, ai_generator=None):
    """Popula a tabela Taxon com hierarquia taxonômica estruturada e válida."""
    try:
        print("Gerando taxonomia estruturada para laboratório científico...")
        
        # Estrutura hierárquica predefinida para garantir consistência
        taxonomia_estruturada = {
            'Dominio': ['Eukarya'],
            'Reino': ['Animalia', 'Plantae', 'Fungi'],
            'Filo': ['Chordata', 'Arthropoda', 'Mollusca', 'Tracheophyta', 'Ascomycota', 'Basidiomycota'],
            'Classe': ['Mammalia', 'Aves', 'Reptilia', 'Actinopterygii', 'Insecta', 'Gastropoda', 'Magnoliopsida', 'Agaricomycetes'],
            'Ordem': ['Primates', 'Carnivora', 'Rodentia', 'Passeriformes', 'Squamata', 'Cypriniformes', 'Lepidoptera', 'Coleoptera', 'Stylommatophora', 'Rosales', 'Agaricales'],
            'Familia': ['Hominidae', 'Felidae', 'Canidae', 'Muridae', 'Corvidae', 'Colubridae', 'Cyprinidae', 'Nymphalidae', 'Scarabaeidae', 'Helicidae', 'Rosaceae', 'Agaricaceae'],
            'Genero': []  # Será gerado pela IA
        }
        
        # Primeiro, insere os níveis predefinidos
        cursor = conexao.cursor()
        registros_inseridos = []
        id_counter = 1
        
        for tipo in ['Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia']:
            for nome in taxonomia_estruturada[tipo]:
                cursor.execute(
                    "INSERT INTO Taxon (ID_Tax, Tipo, Nome) VALUES (%s, %s, %s)",
                    (id_counter, tipo, nome)
                )
                registros_inseridos.append({'ID_Tax': id_counter, 'Tipo': tipo, 'Nome': nome})
                id_counter += 1
        
        # Gera gêneros via IA usando a nova classe
        if ai_generator:
            familias_disponiveis = [r for r in registros_inseridos if r['Tipo'] == 'Familia']
            num_generos = min(n_especies // 3, 50)  # Máximo 50 gêneros
            
            prompt = f"""
Gere {num_generos} nomes de gêneros científicos realísticos para laboratório biológico.

CONTEXTO: Você tem as seguintes famílias disponíveis:
{', '.join([f['Nome'] for f in familias_disponiveis])}

INSTRUÇÕES:
1. Gere nomes de gêneros que sejam taxonomicamente coerentes
2. Use nomenclatura binomial válida (primeira letra maiúscula, itálico não necessário)
3. Diversifique entre animais, plantas e fungos
4. Evite repetições

FORMATO JSON:
{{
    "generos": ["Homo", "Felis", "Canis", "Mus", "Corvus", "Naja", "Danio", "Helix", "Rosa", "Agaricus"]
}}

RESPONDA APENAS COM O JSON.
"""
            
            resposta = ai_generator.generate_data(prompt, modelo="gpt-4o-mini", temperatura=0.4)
            
            if resposta:
                try:
                    resposta_limpa = ai_generator._clean_json_response(resposta)
                    dados_generos = json.loads(resposta_limpa)
                    
                    if 'generos' in dados_generos and dados_generos['generos']:
                        for nome_genero in dados_generos['generos']:
                            cursor.execute(
                                "INSERT INTO Taxon (ID_Tax, Tipo, Nome) VALUES (%s, %s, %s)",
                                (id_counter, 'Genero', str(nome_genero)[:50])
                            )
                            registros_inseridos.append({'ID_Tax': id_counter, 'Tipo': 'Genero', 'Nome': nome_genero})
                            id_counter += 1
                            
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"Erro ao processar gêneros da IA: {e}")
                    # Fallback: gêneros predefinidos
                    generos_fallback = ['Homo', 'Felis', 'Canis', 'Mus', 'Corvus', 'Naja', 'Danio', 'Helix', 'Rosa', 'Agaricus']
                    for nome_genero in generos_fallback:
                        cursor.execute(
                            "INSERT INTO Taxon (ID_Tax, Tipo, Nome) VALUES (%s, %s, %s)",
                            (id_counter, 'Genero', nome_genero)
                        )
                        registros_inseridos.append({'ID_Tax': id_counter, 'Tipo': 'Genero', 'Nome': nome_genero})
                        id_counter += 1
        
        conexao.commit()
        cursor.close()
        
        print(f"✅ Taxonomia estruturada inserida: {len(registros_inseridos)} registros")
        print(f"   Domínios: {len([r for r in registros_inseridos if r['Tipo'] == 'Dominio'])}")
        print(f"   Reinos: {len([r for r in registros_inseridos if r['Tipo'] == 'Reino'])}")
        print(f"   Filos: {len([r for r in registros_inseridos if r['Tipo'] == 'Filo'])}")
        print(f"   Classes: {len([r for r in registros_inseridos if r['Tipo'] == 'Classe'])}")
        print(f"   Ordens: {len([r for r in registros_inseridos if r['Tipo'] == 'Ordem'])}")
        print(f"   Famílias: {len([r for r in registros_inseridos if r['Tipo'] == 'Familia'])}")
        print(f"   Gêneros: {len([r for r in registros_inseridos if r['Tipo'] == 'Genero'])}")
        
        return True
        
    except (mysql.connector.Error, ValueError, KeyError) as e:
        print(f"Erro ao popular Taxon: {e}")
        return False  


def populate_hierarquia_table(conexao):
    """
    Popula a tabela Hierarquia com relacionamentos taxonomicamente válidos.
    """
    try:
        print("Construindo hierarquia taxonômica...")
        
        cursor = conexao.cursor()
        
        # Busca todos os táxons ordenados por tipo hierárquico
        cursor.execute("SELECT ID_Tax, Tipo, Nome FROM Taxon ORDER BY Tipo, Nome")
        todos_taxons = cursor.fetchall()
        
        if not todos_taxons:
            print("Erro: Nenhum táxon encontrado na tabela Taxon")
            return False
        
        # Organiza táxons por tipo
        taxons_por_tipo = {}
        for id_tax, tipo, nome in todos_taxons:
            if tipo not in taxons_por_tipo:
                taxons_por_tipo[tipo] = []
            taxons_por_tipo[tipo].append((id_tax, nome))
        
        print(f"Táxons encontrados por tipo: {[(tipo, len(lista)) for tipo, lista in taxons_por_tipo.items()]}")
        
        # Hierarquia taxonômica padrão
        ordem_hierarquica = ['Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero']
        relacoes_criadas = 0
        
        # Cria relacionamentos hierárquicos
        for i in range(len(ordem_hierarquica) - 1):
            tipo_filho = ordem_hierarquica[i + 1]
            tipo_pai = ordem_hierarquica[i]
            
            if tipo_filho in taxons_por_tipo and tipo_pai in taxons_por_tipo:
                filhos = taxons_por_tipo[tipo_filho]
                pais = taxons_por_tipo[tipo_pai]
                
                # Distribui filhos entre pais
                for j, (id_filho, nome_filho) in enumerate(filhos):
                    # Seleciona pai baseado na distribuição
                    pai_index = j % len(pais)
                    id_pai, nome_pai = pais[pai_index]
                    
                    try:
                        cursor.execute(
                            "INSERT INTO Hierarquia (ID_Tax, ID_TaxTopo) VALUES (%s, %s)",
                            (id_filho, id_pai)
                        )
                        relacoes_criadas += 1
                    except mysql.connector.Error as e:
                        if e.errno != 1062:  # Ignora duplicate key
                            print(f"Erro ao criar relação {nome_filho} → {nome_pai}: {e}")
        
        # Conecta domínios à raiz (se necessário)
        if 'Dominio' in taxons_por_tipo:
            for id_dominio, nome_dominio in taxons_por_tipo['Dominio']:
                try:
                    # Insere domínio como raiz (ID_TaxTopo = NULL ou auto-referência)
                    cursor.execute(
                        "INSERT IGNORE INTO Hierarquia (ID_Tax, ID_TaxTopo) VALUES (%s, NULL)",
                        (id_dominio,)
                    )
                    relacoes_criadas += 1
                except mysql.connector.Error:
                    pass  # Ignora erros
        
        conexao.commit()
        
        # Mostra exemplos das relações criadas
        cursor.execute("""
            SELECT t1.Nome AS Filho, t1.Tipo AS TipoFilho, t2.Nome AS Pai, t2.Tipo AS TipoPai 
            FROM Hierarquia h 
            JOIN Taxon t1 ON h.ID_Tax = t1.ID_Tax 
            LEFT JOIN Taxon t2 ON h.ID_TaxTopo = t2.ID_Tax 
            LIMIT 10
        """)
        exemplos = cursor.fetchall()
        
        if exemplos:
            print("\nExemplos de hierarquia criada:")
            for filho, tipo_filho, pai, tipo_pai in exemplos:
                if pai:
                    print(f"   {filho} ({tipo_filho}) → {pai} ({tipo_pai})")
                else:
                    print(f"   {filho} ({tipo_filho}) → RAIZ")
        
        cursor.close()
        print(f"✅ Hierarquia criada com sucesso: {relacoes_criadas} relações")
        return True
        
    except mysql.connector.Error as e:
        print(f"Erro ao popular Hierarquia: {e}")
        return False


def populate_midia_table(conexao, delay=1):
    """Popula a tabela Midia com imagem da web ou placeholder branco."""

    cursor = conexao.cursor()

    try:
        # Buscar espécimes com nome da espécie
        cursor.execute("""
            SELECT e.ID_Especime, s.Nome 
            FROM Especime e 
            JOIN Especie s ON e.ID_Esp = s.ID_Esp 
            LIMIT 15
        """)
        especimes = cursor.fetchall()

        if not especimes:
            print("⚠️ Nenhum espécime encontrado.")
            return False

        def buscar_imagem(nome_especie):
            """Busca imagem real via DuckDuckGo."""
            try:
                with DDGS() as ddgs:
                    for r in ddgs.images(f"{nome_especie} animal", max_results=5):
                        url = r.get("image")
                        if url:
                            try:
                                resp = requests.get(url, timeout=10)
                                if resp.status_code == 200 and "image" in resp.headers.get("Content-Type", ""):
                                    return resp.content
                            except:
                                continue
            except:
                pass
            return None

        def criar_placeholder_branco(texto, tamanho=(400, 300)):
            """Cria imagem branca simples com texto centralizado."""
            img = Image.new('RGB', tamanho, color='white')
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            except:
                font = ImageFont.load_default()

            text_width = draw.textlength(texto, font=font)
            x = (tamanho[0] - text_width) // 2
            y = (tamanho[1] - 24) // 2

            draw.text((x, y), texto, fill='black', font=font)

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()

        # Loop principal
        sucessos, falhas = 0, 0

        for idx, (id_especime, nome_especie) in enumerate(especimes, 1):
            print(f"[{idx}] Processando: {nome_especie}")

            imagem = buscar_imagem(nome_especie)
            tipo = "Foto científica"

            if not imagem:
                print("   ❌ Imagem não encontrada. Criando placeholder branco.")
                imagem = criar_placeholder_branco(nome_especie)
                tipo = "Placeholder branco"

            if imagem:
                try:
                    cursor.execute(
                        "INSERT INTO Midia (ID_Especime, Tipo, Dado) VALUES (%s, %s, %s)",
                        (id_especime, tipo[:50], imagem)
                    )
                    sucessos += 1
                    print("   ✅ Registro inserido")
                except mysql.connector.Error as e:
                    print(f"   ❌ Erro ao inserir no banco: {e}")
                    falhas += 1
            else:
                print("   ❌ Falha total ao gerar imagem")
                falhas += 1

            time.sleep(delay)

        conexao.commit()
        print(f"\n📊 Finalizado: {sucessos} inserções, {falhas} falhas")
        return sucessos > 0

    except mysql.connector.Error as e:
        print(f"❌ Erro de banco: {e}")
        return False
    finally:
        cursor.close()



def generate_sql_query(user_prompt: str, schema: Dict, conexao=None, modelo: str = "gpt-4o-mini", temperatura: float = 0.3) -> Optional[str]:
    """
    Função única ultra-robusta para geração de SQL complexo usando IA avançada.
    Analisa semanticamente, constrói contexto dinâmico e gera queries sofisticadas.
    """
    if not schema:
        print("❌ Schema não fornecido")
        return "SHOW TABLES;"
    
    # === ANÁLISE SEMÂNTICA AVANÇADA ===
    prompt_lower = user_prompt.lower()
    
    # Detecta intenção e complexidade
    intent = {
        'tipo': 'SELECT',
        'recursos': [],
        'tabelas': [],
        'complexidade': 'simples'
    }
    
    # Análise de operação
    if any(word in prompt_lower for word in ['inserir', 'adicionar', 'criar', 'insert']):
        intent['tipo'] = 'INSERT'
    elif any(word in prompt_lower for word in ['atualizar', 'modificar', 'alterar', 'update']):
        intent['tipo'] = 'UPDATE'
    elif any(word in prompt_lower for word in ['deletar', 'remover', 'excluir', 'delete']):
        intent['tipo'] = 'DELETE'
    
    # Detecta recursos avançados
    resources = {
        'hierarquia': ['hierarquia', 'taxonomia', 'árvore', 'pai', 'filho', 'ancestral', 'descendente', 'classificação'],
        'agregacao': ['total', 'soma', 'média', 'count', 'máximo', 'mínimo', 'grupo', 'agregação', 'estatística'],
        'ranking': ['ranking', 'top', 'maior', 'menor', 'primeiro', 'último', 'melhor', 'pior', 'ordem'],
        'temporal': ['data', 'período', 'ano', 'mês', 'tempo', 'cronológico', 'histórico', 'quando'],
        'analise': ['análise', 'distribuição', 'percentual', 'proporção', 'comparação', 'tendência'],
        'relacional': ['relacionamento', 'associação', 'ligação', 'conexão', 'junto', 'vinculado']
    }
    
    for feature, keywords in resources.items():
        if any(keyword in prompt_lower for keyword in keywords):
            intent['recursos'].append(feature)
    
    # Detecta tabelas relevantes
    table_hints = {
        'taxon': ['taxonomia', 'hierarquia', 'reino', 'filo', 'classe', 'ordem', 'família', 'gênero', 'classificação'],
        'especie': ['espécie', 'species', 'iucn', 'conservação', 'extinção', 'animal', 'planta'],
        'projeto': ['projeto', 'pesquisa', 'estudo', 'investigação', 'trabalho'],
        'funcionario': ['funcionário', 'pesquisador', 'pessoa', 'cientista', 'equipe', 'staff'],
        'amostra': ['amostra', 'coleta', 'material', 'specimen', 'exemplar'],
        'equipamento': ['equipamento', 'instrumento', 'máquina', 'ferramenta', 'aparelho'],
        'laboratorio': ['laboratório', 'lab', 'instalação', 'centro'],
        'midia': ['imagem', 'foto', 'vídeo', 'mídia', 'arquivo']
    }
    
    for table, keywords in table_hints.items():
        if any(keyword in prompt_lower for keyword in keywords):
            intent['tabelas'].append(table)
    
    # Calcula complexidade
    complexity_score = len(intent['recursos'])
    if complexity_score >= 3:
        intent['complexidade'] = 'muito_complexa'
    elif complexity_score >= 2:
        intent['complexidade'] = 'complexa'
    elif complexity_score >= 1:
        intent['complexidade'] = 'moderada'
    
    # === CONTEXTO DINÂMICO INTELIGENTE ===
    context = {'stats': {}, 'samples': {}, 'relationships': {}}
    
    if conexao:
        try:
            cursor = conexao.cursor()
            
            # Estatísticas das tabelas
            for table_name in schema.keys():
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    context['stats'][table_name] = cursor.fetchone()[0]
                except:
                    context['stats'][table_name] = 0
            
            # Amostras de dados baseadas na intenção
            if intent['tabelas']:
                for table in intent['tabelas']:
                    if table in schema:
                        try:
                            cursor.execute(f"SELECT * FROM {table} LIMIT 3")
                            cols = [desc[0] for desc in cursor.description]
                            rows = cursor.fetchall()
                            context['samples'][table] = {'cols': cols, 'data': rows}
                        except:
                            pass
            
            # Dados específicos para recursos detectados
            if 'hierarquia' in intent['recursos']:
                try:
                    cursor.execute("SELECT Tipo, COUNT(*) FROM Taxon GROUP BY Tipo")
                    context['taxonomia'] = cursor.fetchall()
                except:
                    pass
            
            if 'analise' in intent['recursos'] and 'especie' in intent['tabelas']:
                try:
                    cursor.execute("SELECT IUCN, COUNT(*) FROM Especie GROUP BY IUCN")
                    context['iucn_dist'] = cursor.fetchall()
                except:
                    pass
            
            cursor.close()
        except:
            pass
    
    # === PROMPT ULTRA-AVANÇADO PARA IA ===
    api_key = get_openai_key()
    if not api_key:
        return _generate_smart_fallback(user_prompt, intent, schema, context)
    
    # Constrói prompt sofisticado
    prompt_sections = [
        f"PERGUNTA DO USUÁRIO: \"{user_prompt}\"",
        "",
        "=== ANÁLISE SEMÂNTICA ===",
        f"Tipo de operação: {intent['tipo']}",
        f"Complexidade detectada: {intent['complexidade']}",
        f"Recursos necessários: {', '.join(intent['recursos']) if intent['recursos'] else 'consulta básica'}",
        f"Tabelas envolvidas: {', '.join(intent['tabelas']) if intent['tabelas'] else 'a determinar automaticamente'}",
        "",
        "=== SCHEMA COMPLETO ===",
    ]
    
    # Schema detalhado
    for table, columns in schema.items():
        col_info = []
        pks = []
        fks = []
        
        for col in columns:
            col_desc = f"{col['nome']} {col['tipo']}"
            if col.get('nulo') == 'NO':
                col_desc += " NOT NULL"
            if col.get('default'):
                col_desc += f" DEFAULT {col['default']}"
            
            if col.get('chave') == 'PRI':
                pks.append(col['nome'])
            elif col.get('chave') == 'MUL':
                fks.append(col['nome'])
            
            col_info.append(col_desc)
        
        prompt_sections.append(f"TABLE {table}:")
        prompt_sections.append(f"  Colunas: {', '.join(col_info)}")
        if pks:
            prompt_sections.append(f"  PRIMARY KEY: {', '.join(pks)}")
        if fks:
            prompt_sections.append(f"  FOREIGN KEYS: {', '.join(fks)}")
        prompt_sections.append("")
    
    # Contexto dinâmico
    if context['stats']:
        prompt_sections.append("=== ESTATÍSTICAS ATUAIS ===")
        for table, count in context['stats'].items():
            prompt_sections.append(f"{table}: {count:,} registros")
        prompt_sections.append("")
    
    if context['samples']:
        prompt_sections.append("=== DADOS DE EXEMPLO ===")
        for table, data in context['samples'].items():
            prompt_sections.append(f"{table.upper()}:")
            prompt_sections.append(f"  Colunas: {', '.join(data['cols'])}")
            for i, row in enumerate(data['data'][:2]):
                clean_row = []
                for val in row:
                    if isinstance(val, bytes):
                        clean_row.append(f"<BLOB:{len(val)}b>")
                    else:
                        clean_row.append(str(val)[:20])
                prompt_sections.append(f"  Exemplo {i+1}: {' | '.join(clean_row)}")
            prompt_sections.append("")
    
    if 'taxonomia' in context:
        prompt_sections.append("=== DISTRIBUIÇÃO TAXONÔMICA ===")
        for tipo, count in context['taxonomia']:
            prompt_sections.append(f"{tipo}: {count}")
        prompt_sections.append("")
    
    if 'iucn_dist' in context:
        prompt_sections.append("=== STATUS DE CONSERVAÇÃO ===")
        for status, count in context['iucn_dist']:
            prompt_sections.append(f"{status}: {count}")
        prompt_sections.append("")
    
    # Padrões SQL complexos baseados na intenção
    prompt_sections.extend([
        "=== PADRÕES SQL AVANÇADOS ===",
        "",
        "1. HIERARQUIA TAXONÔMICA (CTE Recursiva):",
        "WITH RECURSIVE hierarchy AS (",
        "  SELECT ID_Tax, Nome, Tipo, 0 as nivel, CAST(Nome AS CHAR(500)) as path",
        "  FROM Taxon WHERE Tipo = 'Dominio'",
        "  UNION ALL",
        "  SELECT t.ID_Tax, t.Nome, t.Tipo, h.nivel + 1, CONCAT(h.path, ' > ', t.Nome)",
        "  FROM Taxon t",
        "  JOIN Hierarquia hr ON t.ID_Tax = hr.ID_Tax",
        "  JOIN hierarchy h ON hr.ID_TaxTopo = h.ID_Tax",
        "  WHERE h.nivel < 8",
        ")",
        "SELECT * FROM hierarchy ORDER BY nivel, Nome;",
        "",
        "2. ANÁLISE ESTATÍSTICA AVANÇADA:",
        "SELECT",
        "  t.Nome as Categoria,",
        "  COUNT(DISTINCT e.ID_Esp) as Total_Especies,",
        "  COUNT(CASE WHEN e.IUCN IN ('VU','EN','CR') THEN 1 END) as Ameacadas,",
        "  ROUND(AVG(CASE WHEN e.IUCN IN ('VU','EN','CR') THEN 1 ELSE 0 END) * 100, 2) as Perc_Ameacadas,",
        "  ROW_NUMBER() OVER (ORDER BY COUNT(DISTINCT e.ID_Esp) DESC) as Ranking",
        "FROM Taxon t",
        "LEFT JOIN Especie e ON t.ID_Tax = e.ID_Gen",
        "WHERE t.Tipo = 'Reino'",
        "GROUP BY t.ID_Tax, t.Nome",
        "HAVING COUNT(DISTINCT e.ID_Esp) > 0;",
        "",
        "3. ANÁLISE RELACIONAL COMPLEXA:",
        "SELECT",
        "  p.Nome as Projeto,",
        "  COUNT(DISTINCT pe.ID_Esp) as Especies_Estudadas,",
        "  COUNT(DISTINCT pf.ID_Func) as Pesquisadores,",
        "  GROUP_CONCAT(DISTINCT e.Nome ORDER BY e.Nome SEPARATOR ', ') as Lista_Especies",
        "FROM Projeto p",
        "LEFT JOIN Proj_Esp pe ON p.ID_Proj = pe.ID_Proj",
        "LEFT JOIN Proj_Func pf ON p.ID_Proj = pf.ID_Proj",
        "LEFT JOIN Especie e ON pe.ID_Esp = e.ID_Esp",
        "GROUP BY p.ID_Proj, p.Nome",
        "ORDER BY Especies_Estudadas DESC;",
        "",
        "4. ANÁLISE TEMPORAL:",
        "SELECT",
        "  YEAR(p.Dt_Inicio) as Ano,",
        "  COUNT(*) as Projetos_Iniciados,",
        "  AVG(p.Valor) as Orcamento_Medio,",
        "  SUM(CASE WHEN p.Status = 'Encerrado' THEN 1 ELSE 0 END) as Projetos_Concluidos",
        "FROM Projeto p",
        "GROUP BY YEAR(p.Dt_Inicio)",
        "ORDER BY Ano DESC;",
        "",
        "=== VALORES VÁLIDOS ===",
        "IUCN: LC, NT, VU, EN, CR, EW, EX",
        "Status_Projeto: Planejado, Ativo, Suspenso, Cancelado, Encerrado",
        "Tipos_Taxon: Dominio, Reino, Filo, Classe, Ordem, Familia, Genero",
        "",
        "=== INSTRUÇÕES FINAIS ===",
        f"- Complexidade necessária: {intent['complexidade']}",
        f"- Recursos a usar: {', '.join(intent['recursos']) if intent['recursos'] else 'consulta direta'}",
        "- Otimize para performance (use LIMIT quando apropriado)",
        "- Use JOINs adequados baseados nas FKs mostradas",
        "- Para hierarquias: sempre use CTEs recursivas",
        "- Para rankings: use window functions (ROW_NUMBER, RANK)",
        "- Para agregações: use GROUP BY com funções apropriadas",
        "- Inclua apenas SQL válido e otimizado",
        "",
        "RESPONDA APENAS COM A QUERY SQL FINAL (sem explicações, sem markdown):"
    ])
    
    full_prompt = "\n".join(prompt_sections)
    
    # === CHAMADA À IA ===
    try:
        openai.api_key = api_key
        response = openai.chat.completions.create(
            model=modelo,
            messages=[{
                "role": "system", 
                "content": "Você é um especialista em SQL para sistemas científicos de taxonomia e biodiversidade. Gere apenas SQL otimizado e válido."
            }, {
                "role": "user", 
                "content": full_prompt
            }],
            temperature=temperatura,
            max_tokens=2500
        )
        
        raw_sql = response.choices[0].message.content
        if raw_sql:
            clean_sql = _clean_sql_response(raw_sql)
            if clean_sql and _validate_sql(clean_sql):
                return clean_sql
    
    except Exception as e:
        print(f"⚠️ Erro na IA: {e}")
    
    # === FALLBACK INTELIGENTE ===
    return _generate_smart_fallback(user_prompt, intent, schema, context)


def _clean_sql_response(raw_sql: str) -> Optional[str]:
    """Limpa e extrai SQL válido da resposta da IA."""
    if not raw_sql:
        return None
    
    # Remove markdown
    sql = re.sub(r'```sql\s*', '', raw_sql, flags=re.IGNORECASE)
    sql = re.sub(r'```\s*', '', sql)
    
    # Extrai SQL principal
    lines = sql.split('\n')
    sql_lines = []
    capturing = False
    
    for line in lines:
        line = line.strip()
        
        # Inicia captura em comando SQL
        if any(line.upper().startswith(cmd) for cmd in ['SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE', 'SHOW', 'DESCRIBE']):
            capturing = True
        
        if capturing and line:
            # Para se não for SQL
            if not any(indicator in line.upper() for indicator in [
                'SELECT', 'FROM', 'WHERE', 'JOIN', 'GROUP', 'ORDER', 'HAVING', 'UNION', 'WITH',
                'INSERT', 'UPDATE', 'DELETE', 'SHOW', 'DESCRIBE', 'AND', 'OR', 'AS', 'ON', 'IN',
                'LIKE', 'COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'DISTINCT', 'LIMIT', 'OFFSET',
                '(', ')', ',', ';', '--', '=', '<', '>', 'IS', 'NOT', 'NULL', 'CASE', 'WHEN'
            ]) and not re.match(r'^[A-Za-z_][A-Za-z0-9_]*\s*[=<>!]', line):
                break
            
            sql_lines.append(line)
    
    if not sql_lines:
        return None
    
    # Reconstrói SQL
    clean_sql = ' '.join(sql_lines)
    clean_sql = re.sub(r'\s+', ' ', clean_sql).strip()
    
    # Adiciona ponto e vírgula
    if not clean_sql.endswith(';'):
        clean_sql += ';'
    
    return clean_sql


def _validate_sql(sql: str) -> bool:
    """Validação robusta de SQL."""
    if not sql or len(sql) < 5:
        return False
    
    sql_upper = sql.upper()
    
    # Comandos válidos
    valid_starts = ['SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE', 'SHOW', 'DESCRIBE', 'EXPLAIN']
    if not any(sql_upper.startswith(start) for start in valid_starts):
        return False
    
    # Balanceamento
    if sql.count('(') != sql.count(')'):
        return False
    
    # SELECT deve ter FROM (com exceções)
    if sql_upper.startswith('SELECT') and 'FROM' not in sql_upper:
        if not any(func in sql_upper for func in ['NOW()', 'USER()', 'VERSION()', 'DATABASE()', 'SHOW']):
            return False
    
    # Não deve ter comandos perigosos
    dangerous = ['DROP', 'TRUNCATE', 'ALTER', 'CREATE']
    if any(danger in sql_upper for danger in dangerous):
        return False
    
    return True


def _generate_smart_fallback(user_prompt: str, intent: Dict, schema: Dict, context: Dict) -> str:
    """Fallback inteligente baseado na análise semântica."""
    prompt_lower = user_prompt.lower()
    
    # Fallbacks sofisticados baseados na intenção
    if 'hierarquia' in intent['recursos'] or 'taxonomia' in prompt_lower:
        return """
        WITH RECURSIVE taxonomia_completa AS (
            SELECT ID_Tax, Nome, Tipo, 0 as nivel, CAST(Nome AS CHAR(500)) as caminho_completo
            FROM Taxon WHERE Tipo = 'Dominio'
            UNION ALL
            SELECT t.ID_Tax, t.Nome, t.Tipo, tc.nivel + 1, 
                   CONCAT(tc.caminho_completo, ' → ', t.Nome) as caminho_completo
            FROM Taxon t 
            JOIN Hierarquia h ON t.ID_Tax = h.ID_Tax
            JOIN taxonomia_completa tc ON h.ID_TaxTopo = tc.ID_Tax
            WHERE tc.nivel < 10
        )
        SELECT nivel, Tipo, Nome, caminho_completo 
        FROM taxonomia_completa 
        ORDER BY nivel, Tipo, Nome 
        LIMIT 100;
        """
    
    elif 'ranking' in intent['recursos'] and ('projeto' in intent['tabelas'] or 'projeto' in prompt_lower):
        return """
        SELECT 
            p.Nome as Projeto,
            p.Status,
            p.Valor as Orcamento,
            COUNT(DISTINCT pe.ID_Esp) as Especies_Estudadas,
            COUNT(DISTINCT pf.ID_Func) as Pesquisadores_Envolvidos,
            DATEDIFF(COALESCE(p.Dt_Fim, CURDATE()), p.Dt_Inicio) as Duracao_Dias,
            ROW_NUMBER() OVER (ORDER BY p.Valor DESC) as Ranking_Por_Orcamento,
            ROW_NUMBER() OVER (ORDER BY COUNT(DISTINCT pe.ID_Esp) DESC) as Ranking_Por_Especies,
            RANK() OVER (ORDER BY COUNT(DISTINCT pf.ID_Func) DESC) as Ranking_Por_Equipe
        FROM Projeto p
        LEFT JOIN Proj_Esp pe ON p.ID_Proj = pe.ID_Proj
        LEFT JOIN Proj_Func pf ON p.ID_Proj = pf.ID_Proj
        GROUP BY p.ID_Proj, p.Nome, p.Status, p.Valor, p.Dt_Inicio, p.Dt_Fim
        ORDER BY Especies_Estudadas DESC, Orcamento DESC
        LIMIT 20;
        """
    
    elif 'analise' in intent['recursos'] and 'especie' in intent['tabelas']:
        return """
        SELECT 
            t.Nome as Reino,
            COUNT(DISTINCT e.ID_Esp) as Total_Especies,
            COUNT(DISTINCT CASE WHEN e.IUCN IN ('VU','EN','CR','EW','EX') THEN e.ID_Esp END) as Especies_Ameacadas,
            COUNT(DISTINCT CASE WHEN e.IUCN = 'LC' THEN e.ID_Esp END) as Especies_Seguras,
            ROUND(AVG(CASE WHEN e.IUCN IN ('VU','EN','CR','EW','EX') THEN 1 ELSE 0 END) * 100, 2) as Percentual_Ameacadas,
            ROW_NUMBER() OVER (ORDER BY COUNT(DISTINCT e.ID_Esp) DESC) as Ranking_Diversidade
        FROM Taxon t
        JOIN Hierarquia h ON t.ID_Tax = h.ID_TaxTopo
        JOIN Taxon t2 ON h.ID_Tax = t2.ID_Tax
        JOIN Especie e ON t2.ID_Tax = e.ID_Gen
        WHERE t.Tipo = 'Reino'
        GROUP BY t.ID_Tax, t.Nome
        HAVING COUNT(DISTINCT e.ID_Esp) > 0
        ORDER BY Total_Especies DESC
        LIMIT 15;
        """
    
    elif 'temporal' in intent['recursos']:
        return """
        SELECT 
            YEAR(p.Dt_Inicio) as Ano_Inicio,
            QUARTER(p.Dt_Inicio) as Trimestre,
            COUNT(*) as Projetos_Iniciados,
            COUNT(CASE WHEN p.Status = 'Encerrado' THEN 1 END) as Projetos_Concluidos,
            AVG(p.Valor) as Orcamento_Medio,
            SUM(p.Valor) as Orcamento_Total,
            COUNT(DISTINCT pe.ID_Esp) as Total_Especies_Estudadas
        FROM Projeto p
        LEFT JOIN Proj_Esp pe ON p.ID_Proj = pe.ID_Proj
        WHERE p.Dt_Inicio >= '2020-01-01'
        GROUP BY YEAR(p.Dt_Inicio), QUARTER(p.Dt_Inicio)
        ORDER BY Ano_Inicio DESC, Trimestre DESC
        LIMIT 20;
        """
    
    elif 'funcionario' in intent['tabelas'] or 'pesquisador' in prompt_lower:
        return """
        SELECT 
            f.Nome as Pesquisador,
            f.Cargo,
            f.Email,
            COUNT(DISTINCT pf.ID_Proj) as Projetos_Participacao,
            COUNT(DISTINCT a.ID_Amostra) as Amostras_Coletadas,
            COUNT(DISTINCT ru.ID_Equip) as Equipamentos_Utilizados,
            GROUP_CONCAT(DISTINCT p.Nome ORDER BY p.Nome SEPARATOR '; ') as Lista_Projetos
        FROM Funcionario f
        LEFT JOIN Proj_Func pf ON f.ID_Func = pf.ID_Func
        LEFT JOIN Projeto p ON pf.ID_Proj = p.ID_Proj
        LEFT JOIN Amostra a ON f.ID_Func = a.ID_Func
        LEFT JOIN Registro_de_Uso ru ON f.ID_Func = ru.ID_Func
        GROUP BY f.ID_Func, f.Nome, f.Cargo, f.Email
        ORDER BY Projetos_Participacao DESC, Amostras_Coletadas DESC
        LIMIT 25;
        """
    
    elif 'todas' in prompt_lower and 'espécie' in prompt_lower:
        return """
        SELECT 
            CONCAT(tg.Nome, ' ', e.Nome) as Nome_Cientifico,
            e.Nome_Pop as Nome_Popular,
            e.IUCN as Status_Conservacao,
            e.Habitat,
            e.Caracteristicas,
            tf.Nome as Familia,
            to_tax.Nome as Ordem,
            tc.Nome as Classe
        FROM Especie e
        JOIN Taxon tg ON e.ID_Gen = tg.ID_Tax
        LEFT JOIN Hierarquia hf ON tg.ID_Tax = hf.ID_Tax
        LEFT JOIN Taxon tf ON hf.ID_TaxTopo = tf.ID_Tax AND tf.Tipo = 'Familia'
        LEFT JOIN Hierarquia ho ON tf.ID_Tax = ho.ID_Tax
        LEFT JOIN Taxon to_tax ON ho.ID_TaxTopo = to_tax.ID_Tax AND to_tax.Tipo = 'Ordem'
        LEFT JOIN Hierarquia hc ON to_tax.ID_Tax = hc.ID_Tax
        LEFT JOIN Taxon tc ON hc.ID_TaxTopo = tc.ID_Tax AND tc.Tipo = 'Classe'
        ORDER BY Nome_Cientifico
        LIMIT 50;
        """
    
    elif any(word in prompt_lower for word in ['contagem', 'total', 'quantos', 'estatística']):
        return """
        SELECT 
            'Domínios' as Categoria, COUNT(*) as Total FROM Taxon WHERE Tipo = 'Dominio'
        UNION ALL
        SELECT 'Reinos' as Categoria, COUNT(*) as Total FROM Taxon WHERE Tipo = 'Reino'
        UNION ALL
        SELECT 'Filos' as Categoria, COUNT(*) as Total FROM Taxon WHERE Tipo = 'Filo'
        UNION ALL
        SELECT 'Classes' as Categoria, COUNT(*) as Total FROM Taxon WHERE Tipo = 'Classe'
        UNION ALL
        SELECT 'Ordens' as Categoria, COUNT(*) as Total FROM Taxon WHERE Tipo = 'Ordem'
        UNION ALL
        SELECT 'Famílias' as Categoria, COUNT(*) as Total FROM Taxon WHERE Tipo = 'Familia'
        UNION ALL
        SELECT 'Gêneros' as Categoria, COUNT(*) as Total FROM Taxon WHERE Tipo = 'Genero'
        UNION ALL
        SELECT 'Espécies' as Categoria, COUNT(*) as Total FROM Especie
        UNION ALL
        SELECT 'Projetos' as Categoria, COUNT(*) as Total FROM Projeto
        UNION ALL
        SELECT 'Funcionários' as Categoria, COUNT(*) as Total FROM Funcionario
        ORDER BY Total DESC;
        """
    
    else:
        # Fallback genérico inteligente
        if context['stats']:
            # Se tem estatísticas, mostra resumo
            return """
            SELECT table_name as Tabela, table_rows as Registros_Estimados
            FROM information_schema.tables 
            WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
            ORDER BY table_rows DESC;
            """
        else:
            return "SHOW TABLES;"


