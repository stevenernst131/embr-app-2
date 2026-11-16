import { ManagedIdentityCredential } from "@azure/identity";
import { SecretClient } from "@azure/keyvault-secrets";
import { CosmosClient } from "@azure/cosmos";

const credential = new ManagedIdentityCredential();
export const log = (event, details = {}) => console.log(JSON.stringify({ timestamp: new Date().toISOString(), event, ...details }));
export const failure = (event, error, requestId) => console.error(JSON.stringify({ timestamp: new Date().toISOString(), event, requestId, errorName: error.name, code: error.code, statusCode: error.statusCode, message: error.message?.slice(0, 500) }));
export function secretClient() { return new SecretClient(process.env.CONNECTION_KEY_VAULT_ENDPOINT, credential); }
export function itemsContainer() {
  const client = new CosmosClient({ endpoint: process.env.CONNECTION_COSMOS_ENDPOINT, aadCredentials: credential, connectionPolicy: { requestTimeout: 10000 } });
  return client.database(process.env.CONNECTION_COSMOS_DATABASE).container(process.env.CONNECTION_COSMOS_CONTAINER);
}
