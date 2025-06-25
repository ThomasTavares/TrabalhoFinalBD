CREATE TABLE Taxon (
	ID_Tax integer PRIMARY KEY,
	Tipo varchar(10),
	Nome varchar(50),
	CHECK (Tipo IN ('Domínio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Família', 'Gênero')));

CREATE TABLE Hierarquia (
	ID_Tax integer PRIMARY KEY,
	ID_TaxTopo integer,
	FOREIGN KEY(ID_Tax) REFERENCES Taxon (ID_Tax),
	FOREIGN KEY(ID_TaxTopo) REFERENCES Taxon (ID_Tax));

CREATE TABLE Especie (
	ID_Esp integer PRIMARY KEY,
	ID_Gen integer,
	Nome varchar(50),
	Nome_Pop varchar(50),
	Descricao varchar(2500),
	IUCN varchar(2),
	FOREIGN KEY(ID_Gen) REFERENCES Taxon (ID_Tax));

CREATE TABLE Especime (
	ID_Especime integer PRIMARY KEY,
	ID_Esp integer,
	Descritivo varchar(50),
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp));

CREATE TABLE Local_de_Coleta (
	ID_Local integer PRIMARY KEY,
	Nome varchar(50),
	Endereco varchar(100));

CREATE TABLE Amostra (
	ID_Amos integer PRIMARY KEY,
	ID_Esp integer,
	ID_Local integer,
	Tipo varchar(50),
	Dt_Coleta date,
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp),
	FOREIGN KEY(ID_Local) REFERENCES Local_de_Coleta (ID_Local));

CREATE TABLE Midia (
	ID_Midia integer PRIMARY KEY,
	ID_Especime integer,
	Tipo varchar(50),
	Dado blob,	-- BLOB = Binary Large Object
	FOREIGN KEY(ID_Especime) REFERENCES Especime (ID_Especime));

CREATE TABLE Projeto (
	ID_Proj integer PRIMARY KEY,
	Nome varchar(50),
	Descricao varchar(100),
	Status varchar(50),
	Dt_Inicio date,
	Dt_Fim date);
    
CREATE TABLE Artigo (
	ID_Artigo integer PRIMARY KEY,
	ID_Proj integer,
	Titulo varchar(50),
	Resumo varchar(2500),
	DOI varchar(50),
	Link varchar(100),
	Dt_Pub date,
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj));

CREATE TABLE Funcionario (
	ID_Func integer PRIMARY KEY,
	Nome varchar(50),
	CPF varchar(11),
	Cargo varchar(50));
    
CREATE TABLE Proj_Func (
	ID_Proj integer,
	ID_Func integer,
	PRIMARY KEY(ID_Proj, ID_Func),
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func));
    
CREATE TABLE Proj_Esp (
	ID_Proj integer,
	ID_Esp integer,
	PRIMARY KEY(ID_Proj,ID_Esp),
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp));

CREATE TABLE Categoria (
	ID_Categ integer PRIMARY KEY,
	Descritivo varchar(50));

CREATE TABLE Proj_Cat (
	ID_Proj integer,
	ID_Categ integer,
	PRIMARY KEY(ID_Proj,ID_Categ),
	FOREIGN KEY(ID_Categ) REFERENCES Categoria (ID_Categ));

CREATE TABLE Laboratorio (
	ID_Lab integer PRIMARY KEY,
	Nome varchar(50),
	Endereco varchar(100));

CREATE TABLE Contrato (
	ID_Contrato integer PRIMARY KEY,
	ID_Func integer,
	ID_Lab integer,
	Status varchar(50),
	Dt_Inicio date,
	Dt_Fim date,
	Valor decimal(10,2),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func),
	FOREIGN KEY(ID_Lab) REFERENCES Laboratorio (ID_Lab));

CREATE TABLE Financiador (
	ID_Financiador integer PRIMARY KEY,
	Descritivo varchar(50),
	Endereco varchar(100));

CREATE TABLE Financiamento (
	ID_Financiamento integer PRIMARY KEY,
	ID_Proj integer,
	ID_Financiador integer,
	Valor decimal(10,2),
	Dt_Financ date,
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Financiador) REFERENCES Financiador (ID_Financiador));

CREATE TABLE Equipamento (
	ID_Equip integer PRIMARY KEY,
	ID_Lab integer,
	Tipo varchar(50),
	Modelo varchar(50),
	FOREIGN KEY(ID_Lab) REFERENCES Laboratorio (ID_Lab));

CREATE TABLE Registro_de_Uso (
	ID_Func integer,
	ID_Equip integer,
	Dt_Reg timestamp,
	PRIMARY KEY(ID_Func,ID_Equip),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func),
	FOREIGN KEY(ID_Equip) REFERENCES Equipamento (ID_Equip));