export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    console.log(JSON.stringify({ timestamp: new Date().toISOString(), event: "startup.config", credential: "ManagedIdentityCredential", keyVaultConfigured: !!process.env.CONNECTION_KEY_VAULT_ENDPOINT, cosmosConfigured: !!process.env.CONNECTION_COSMOS_ENDPOINT, database: process.env.CONNECTION_COSMOS_DATABASE, container: process.env.CONNECTION_COSMOS_CONTAINER }));
  }
}
