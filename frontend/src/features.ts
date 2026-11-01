/**
 * Temporary feature switches.
 *
 * SOCIAL_FEATURES_ENABLED gates only the *entry points* for the social
 * features ("Add Friends" panel on Profile, "Play With Friends" buttons on
 * the Games screen). The components, screens, routes, and API client code
 * are untouched — flip this back to `true` to restore the features with no
 * other changes. No backend endpoint, database structure, or schema was
 * modified or removed.
 */
export const SOCIAL_FEATURES_ENABLED = false;
