export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    console.log(JSON.stringify({ timestamp: new Date().toISOString(), event: "startup.config", credential: "ManagedIdentityCredential", keyVaultConfigured: !!process.env.KEY_VAULT_URI, cosmosConfigured: !!process.env.COSMOS_ENDPOINT, database: process.env.COSMOS_DATABASE, container: process.env.COSMOS_CONTAINER }));
  }
}
