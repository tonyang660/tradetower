import type { ConfigurationBootstrapResponse } from "./configuration";
import type { SystemHealthBootstrapResponse } from "./systemHealth";

export type SystemHealthPageV2Response = SystemHealthBootstrapResponse & {
  partial?: boolean;
  system_configuration_page_v2_version?: string;
  v2?: {
    source?: string;
    compatibility_mode?: boolean;
    page_owner?: string;
    notes?: string[];
  };
};

export type ConfigurationPageV2Response = ConfigurationBootstrapResponse & {
  partial?: boolean;
  system_configuration_page_v2_version?: string;
  v2?: {
    source?: string;
    compatibility_mode?: boolean;
    page_owner?: string;
    write_paths_preserved?: string[];
    notes?: string[];
  };
};
