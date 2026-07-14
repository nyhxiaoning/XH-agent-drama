export type ModelLibraryCategoryId = "convenience" | "home" | "outdoor" | "tools" | "my-models";

export type ModelLibraryCategory = {
  directoryName: string;
  id: ModelLibraryCategoryId;
  label: string;
};

export type ModelLibraryItem = {
  categoryId: ModelLibraryCategoryId;
  fileName: string;
  id: string;
  name: string;
  thumbUrl?: string;
  url: string;
};

export const MODEL_LIBRARY_CATEGORIES: ModelLibraryCategory[] = [
  { id: "convenience", label: "便利生活", directoryName: "便利生活" },
  { id: "home", label: "居家生活", directoryName: "生活家居" },
  { id: "outdoor", label: "户外出行", directoryName: "户外出行" },
  { id: "tools", label: "工具配件", directoryName: "工具配件" },
  { id: "my-models", label: "我的模型", directoryName: "" },
];

export function getModelLibraryItems(): ModelLibraryItem[] {
  return [];
}
