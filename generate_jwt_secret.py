"""
Script para gerar JWT_SECRET seguro para produção
Execute: python generate_jwt_secret.py
"""
import secrets

def generate_jwt_secret():
    """Gera uma chave secreta segura para JWT"""
    # Gera 64 bytes (512 bits) de dados aleatórios e converte para hex
    secret = secrets.token_hex(64)
    print("=" * 70)
    print("JWT_SECRET gerado com sucesso!")
    print("=" * 70)
    print()
    print("Adicione esta linha no arquivo .env e nas variáveis de ambiente:")
    print()
    print(f"JWT_SECRET={secret}")
    print()
    print("=" * 70)
    print("IMPORTANTE:")
    print("- Guarde esta chave em local seguro")
    print("- NUNCA compartilhe ou commite no Git")
    print("- Use a mesma chave em todos os ambientes de produção")
    print("=" * 70)
    return secret

if __name__ == "__main__":
    generate_jwt_secret()
