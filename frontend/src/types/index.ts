export type UserProfile = {
  id: string;
  username: string;
  role: string;
  permissions: string[];
  is_active: boolean;
  created_at: string;
};

export type KnowledgeDocument = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  chunk_count: number;
};
