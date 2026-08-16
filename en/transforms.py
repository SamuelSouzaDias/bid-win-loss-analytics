# Core transformation logic for the Bid Win/Loss Analytics pipeline: denull,
# is_bulk_load derivation, the SCD Type 2 client dimension, and the
# point-in-time join. Imported directly by 02_silver_bids and
# 03_gold_bid_performance (and 04_analysis's regression cell) -- this is
# the single source of truth for that logic, not a copy of it.
#
# Every function takes and returns a PySpark DataFrame and touches no
# external state (no reads, no writes, no spark.table(...)), which is what
# makes them testable with a local SparkSession and no Databricks
# connection (see tests/test_transforms.py).

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def denull(df: DataFrame, placeholders=("null", "-", "")) -> DataFrame:
    # Replace placeholder strings with true NULLs across all string columns.
    for c, t in df.dtypes:
        if t == "string":
            df = df.withColumn(
                c,
                F.when(F.trim(F.col(c)).isin(list(placeholders)), None).otherwise(
                    F.col(c)
                ),
            )
    return df


def add_is_bulk_load(df: DataFrame, threshold: int = 10) -> DataFrame:
    # Flag rows whose created_at is shared by threshold or more rows.
    batch = Window.partitionBy("created_at")
    return (
        df.withColumn("_batch_size", F.count("*").over(batch))
        .withColumn("is_bulk_load", (F.col("_batch_size") >= threshold).cast("boolean"))
        .drop("_batch_size")
    )


def flag_placeholder_competitor(
    df: DataFrame, placeholder: str = "Competitor 1"
) -> DataFrame:
    # Add competitor_is_placeholder and has_loss_reason flags.
    return df.withColumn(
        "competitor_is_placeholder",
        (F.col("competitor_name") == F.lit(placeholder)).cast("boolean"),
    ).withColumn("has_loss_reason", F.col("loss_reason").isNotNull())


def build_client_scd2(df: DataFrame, sentinel: str = "2999-12-31") -> DataFrame:
    # Turn a raw clients DataFrame into an SCD Type 2 dimension. Expects
    # client_id, start_date, end_date as strings (as they arrive from
    # Bronze). Adds is_open_ended, casts dates, and derives valid_from /
    # valid_to (exclusive; NULL = current) / is_current / client_sk.
    typed = (
        df.withColumn("client_id", F.col("client_id").cast("long"))
        .withColumn(
            "is_open_ended", (F.col("end_date").startswith(sentinel)).cast("boolean")
        )
        .withColumn(
            "end_date",
            F.when(F.col("end_date").startswith(sentinel), None).otherwise(
                F.to_date("end_date")
            ),
        )
        .withColumn("start_date", F.to_date("start_date"))
    )

    version_order = Window.partitionBy("client_id").orderBy(
        F.col("start_date").asc_nulls_first(), F.col("end_date").asc_nulls_last()
    )

    return (
        typed.withColumn("valid_from", F.col("start_date"))
        .withColumn("valid_to", F.lead("start_date").over(version_order))
        .withColumn("is_current", F.col("valid_to").isNull())
        .withColumn("client_sk", F.monotonically_increasing_id())
    )


def point_in_time_join(
    bids: DataFrame,
    clients_scd2: DataFrame,
    client_cols=(
        "client_sk",
        "is_current",
        "segment",
        "state",
        "city",
        "account_executive",
        "director",
        "manager",
        "coordinator",
    ),
) -> DataFrame:
    # Join bids to the client version valid at bids.created_at. bids must
    # have client_id and created_at (timestamp). clients_scd2 must be the
    # output of build_client_scd2. Rows with no matching client version get
    # NULL for every column in client_cols rather than being dropped --
    # mirrors the LEFT join used in 03_gold_bid_performance.ipynb and
    # 04_analysis.ipynb.
    b = bids.alias("b")
    c = clients_scd2.alias("c")

    joined = b.join(
        c,
        (F.col("b.client_id") == F.col("c.client_id"))
        & (F.col("b.created_at") >= F.col("c.valid_from").cast("timestamp"))
        & (
            F.col("c.valid_to").isNull()
            | (F.col("b.created_at") < F.col("c.valid_to").cast("timestamp"))
        ),
        "left",
    )

    select_cols = ["b.*"] + [F.col(f"c.{col}") for col in client_cols]
    return joined.select(*select_cols)