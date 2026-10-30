/* Shared TagEditor i18n strings (see ec2/InstanceDetail.jsx for the canonical copy). */
export const TAG_I18N = {
  keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
  undoPrompt: "This tag will be removed upon saving changes", loading: "Loading tags", keyPlaceholder: "Enter key",
  valuePlaceholder: "Enter value", emptyTags: "No tags associated with the resource.", tooManyKeysSuggestion: "", tooManyValuesSuggestion: "",
  keysSuggestionLoading: "", keysSuggestionError: "", valuesSuggestionLoading: "", valuesSuggestionError: "",
  emptyKeyError: "You must specify a tag key", maxKeyCharLengthError: "Max 128 characters", maxValueCharLengthError: "Max 256 characters",
  duplicateKeyError: "You must specify a unique tag key.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.",
  awsPrefixError: "Cannot start with aws:", tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
};
