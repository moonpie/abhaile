const omadaUsername = process.env.OMADA_MONGODB_USERNAME;
const omadaPassword = process.env.OMADA_MONGODB_PASSWORD;

if (!omadaUsername || !omadaPassword) {
  throw new Error("OMADA_MONGODB_USERNAME and OMADA_MONGODB_PASSWORD must be set");
}

db = db.getSiblingDB("omada");

db.createUser({
  user: omadaUsername,
  pwd: omadaPassword,
  roles: [
    { role: "dbOwner", db: "omada" },
    { role: "dbOwner", db: "omada_data" }
  ]
});
